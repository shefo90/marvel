"""Catalog reads and writes for the operator's back-office.

Deliberately not built on ``repositories.product``. The public listing answers
"what may a shopper and a crawler see" — it filters to ``status='active'`` with a
published translation for one locale, and it is cached. The operator needs the
opposite: everything regardless of status, no locale scoping, and no cache,
because they are looking for the work that is *not* finished yet.

Bending one function to serve both would mean a boolean parameter that silently
decides whether unpublished products leak onto the storefront. Two functions
cannot make that mistake.

Query count is constant regardless of page size — three statements: the page,
its translations, and the total. ``scripts/check_query_count.py`` enforces a
budget on the public listing for the same reason.
"""

import hashlib
import re
import secrets
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.categories import Category
from models.product_images import ProductImage
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from repositories.admin_slugs import (
    normalize_translation_slug,
    record_slug_change,
    release_live_path,
)
from services import cache
from services.role_access_level import LEVEL_ADMIN, set_access_level

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# product_variants.sku is String(64). The SKU is built from item_group_id plus
# the size and the colour, so a group id that fits its own String(64) column can
# still overflow this one.
_SKU_MAX_LENGTH = 64

# ck_product_translations_published_requires_content
_PUBLISHABLE_FIELDS = ("title", "description", "meta_description")


def _missing_publishable_fields(tr) -> list[str]:
    """Which fields ck_product_translations_published_requires_content still needs.

    ONE implementation, called by both upsert_translation and publish_readiness.
    They previously disagreed -- ``is None`` in one, falsiness in the other -- so
    an empty or whitespace-only title published through upsert_translation while
    publish_readiness would have refused it. The CHECK cannot close that gap on
    its own: it is NULL-only, and "" IS NOT NULL. services/identity.py's
    docstring records the same failure mode for customer identity: two
    implementations of one rule that drifted apart.
    """
    return [f for f in _PUBLISHABLE_FIELDS if not (getattr(tr, f, None) or "").strip()]


def list_products_for_admin(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    """Paged product listing for the back-office, drafts included.

    ``status`` filters to one lifecycle state; ``search`` matches the base title
    or slug. Both are optional — the default view is everything, newest first,
    which is what an operator wants after adding a product.
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    variant_count = (
        select(func.count())
        .select_from(ProductVariant)
        .where(ProductVariant.product_id == Product.id)
        .scalar_subquery()
    )
    image_count = (
        select(func.count())
        .select_from(ProductImage)
        .where(ProductImage.product_id == Product.id)
        .scalar_subquery()
    )

    stmt = select(Product, variant_count, image_count)
    count_stmt = select(func.count()).select_from(Product)

    if status:
        stmt = stmt.where(Product.status == status)
        count_stmt = count_stmt.where(Product.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        # Base title/slug only. The operator searches for what they typed when
        # creating the product; translated titles are found on the edit screen.
        condition = Product.title.ilike(pattern) | Product.slug.ilike(pattern)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    rows = db.execute(
        stmt.order_by(Product.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    products = [r[0] for r in rows]
    ids = [p.id for p in products]

    by_product: dict[int, list] = {pid: [] for pid in ids}
    if ids:
        for tr in db.execute(
            select(ProductTranslation).where(ProductTranslation.product_id.in_(ids))
        ).scalars():
            by_product[tr.product_id].append(
                {
                    "locale": tr.locale,
                    "is_published": tr.is_published,
                    "is_complete": tr.is_complete,
                }
            )

    return {
        "items": [
            {
                "id": p.id,
                "slug": p.slug,
                "title": p.title,
                "brand": p.brand,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "variant_count": vc,
                "image_count": ic,
                "translations": sorted(
                    by_product[p.id], key=lambda t: t["locale"]
                ),
            }
            for p, vc, ic in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": db.execute(count_stmt).scalar_one(),
    }


# The UNIQUE constraints a caller can actually collide with, and the sentence
# that names the field they must change. Anything else -- a NOT NULL, a CHECK,
# a foreign key -- is not a conflict and must never be reported as one.
_UNIQUE_CONFLICTS = {
    "uq_products_slug": "slug already in use",
    "uq_products_item_group_id": "item group id already in use",
}


def _conflict(exc: IntegrityError) -> HTTPException:
    """Turn a UNIQUE violation into a 409 that names the colliding field.

    Both write paths previously answered "slug already in use" for *every*
    IntegrityError, so ``PATCH {"title": null}`` -- a NOT NULL violation -- came
    back as a slug collision the operator could not find anywhere. psycopg2
    reports which constraint actually fired on ``exc.orig.diag``; an unmapped
    one is re-raised rather than guessed at, because a wrong 409 costs more
    than an honest 500. Both attributes are read defensively: ``orig`` is the
    DBAPI error SQLAlchemy wrapped, and only psycopg2 guarantees ``diag``.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    detail = _UNIQUE_CONFLICTS.get(getattr(diag, "constraint_name", None) or "")
    if detail is None:
        raise exc
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _generate_item_group_id(slug: str) -> str:
    """Merchant's variant-grouping key. Derived, never typed.

    Uppercased alphanumerics from the slug plus a short random suffix, because
    item_group_id is UNIQUE and two products may share a slug stem across
    categories.
    """
    stem = re.sub(r"[^A-Z0-9]", "", slug.upper())[:16] or "PROD"
    return f"{stem}-{secrets.token_hex(3).upper()}"


def create_product(db: Session, actor, payload: dict) -> Product:
    """Create a product in draft. Nothing is published by this call."""
    slug = (payload.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="slug must be lowercase letters, digits and single hyphens",
        )

    category_id = payload.get("category_id")
    category = db.get(Category, category_id) if category_id is not None else None
    if category is None or category.level != 2:
        # products.category_level is GENERATED ALWAYS AS 2 with a composite FK,
        # so a level-1 category fails as an unreadable FK violation otherwise.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="products attach to level-2 categories only",
        )

    if db.execute(select(Product.id).where(Product.slug == slug)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slug already in use"
        )

    # Keys the caller omitted are left out of the constructor entirely rather
    # than passed as None. gender carries a server_default (this is a women's
    # footwear store, and section 8 requires gender on every apparel offer for
    # Merchant Center): SQLAlchemy currently omits a None-valued, server-
    # defaulted attribute from the INSERT and lets the database supply it, but
    # that is ORM behaviour we should not depend on staying that way — a
    # future Python-side `default=` on the column, for instance, would not get
    # the same treatment and an explicit None would win outright.
    fields = {
        "item_group_id": payload.get("item_group_id") or _generate_item_group_id(slug),
        "slug": slug,
        "title": payload["title"].strip(),
        "description": payload.get("description"),
        "brand": payload.get("brand") or "Pixi",
        "category_id": category.id,
        "tags": payload.get("tags") or [],
        "condition": payload.get("condition") or "new",
        "status": "draft",
    }
    if payload.get("gender") is not None:
        fields["gender"] = payload["gender"]
    if payload.get("age_group") is not None:
        fields["age_group"] = payload["age_group"]

    product = Product(**fields)
    db.add(product)
    try:
        db.flush()
    except IntegrityError as exc:
        # The pre-check above handles the common case cheaply; this catches a
        # concurrent insert of the same slug that lands between the pre-check
        # and this flush (repositories/register.py has the same pattern for
        # uq_users_email) -- and item_group_id, which has no pre-check at all.
        db.rollback()
        raise _conflict(exc)
    return product


def upsert_translation(db: Session, actor, product_id: int, locale: str, payload: dict) -> ProductTranslation:
    """Create or update one locale's content. Publishing is per-language.

    is_complete is derived, never taken from the caller: it means "has every
    field the publish CHECK requires", so the operator's readiness view cannot
    disagree with what the database will actually accept.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one_or_none()

    is_new = tr is None
    if is_new:
        tr = ProductTranslation(
            product_id=product_id, locale=locale,
            translation_source="human", is_published=False,
        )
        db.add(tr)

    old_slug = None if is_new else tr.slug
    was_published = False if is_new else tr.is_published

    for field in ("title", "description", "seo_title", "meta_description",
                  "og_title", "og_description", "og_image_url", "image_alt"):
        if field in payload:
            setattr(tr, field, payload[field])

    if payload.get("slug"):
        tr.slug = normalize_translation_slug(payload["slug"])
    elif is_new:
        tr.slug = normalize_translation_slug(payload.get("title") or product.slug)

    # Whether the row *ends up* published, not whether this call asked to
    # publish: emptying a field on an already-published translation reaches the
    # same forbidden state, and gating on the payload alone missed it.
    will_be_published = bool(
        payload["is_published"] if "is_published" in payload else tr.is_published
    )
    if will_be_published:
        # ck_product_translations_published_requires_content would otherwise
        # turn this into an unhandled IntegrityError -> 500 at flush.
        missing = _missing_publishable_fields(tr)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"cannot publish: missing {', '.join(missing)}",
            )

    if "is_published" in payload:
        tr.is_published = bool(payload["is_published"])

    db.flush()
    db.refresh(tr)

    slug_changed = old_slug is not None and old_slug != tr.slug
    if is_new or slug_changed:
        # Whatever path this translation now occupies is live, so any redirect
        # pointing away from it must stop firing first -- see release_live_path.
        release_live_path(db, locale=locale, slug=tr.slug)
        # A draft has never been indexed, so a redirect from it would be noise.
        if was_published and slug_changed:
            record_slug_change(
                db, locale=locale, old_slug=old_slug,
                product_id=product_id, actor_id=actor.id,
            )
        db.flush()

    stale = [(locale, old_slug)] if slug_changed else None
    _invalidate(db, product_id, stale)
    return tr


def _invalidate(
    db: Session, product_id: int, stale: list[tuple[str, str]] | None = None
) -> None:
    """Drop every cached copy of this product, in every locale it has.

    invalidate_product's docstring is explicit that a missing locale leaves that
    locale serving stale content, so the map is read from the rows rather than
    assumed. ``stale`` carries (locale, slug) pairs that are no longer on any
    row — a slug a caller just renamed away from — so the entry cached under
    the retired slug (``repositories.product.get_product_by_slug`` keys on it)
    is dropped immediately instead of waiting out its TTL.
    """
    slugs = {
        loc: slug
        for loc, slug in db.execute(
            select(ProductTranslation.locale, ProductTranslation.slug).where(
                ProductTranslation.product_id == product_id
            )
        ).all()
    }
    cache.invalidate_product(product_id, slugs)
    if stale:
        cache.delete(*(cache.key(cache.NS_PRODUCT, loc, slug) for loc, slug in stale))


def _clean_sku_segment(raw: str) -> str:
    """ASCII letters, digits and hyphens only, upper-cased — exactly what
    ck_variants_sku_format (^[A-Z0-9][A-Z0-9-]*$) allows inside a segment.

    ``str.isalnum()``/``str.upper()`` are Unicode-aware, so an Arabic colour
    name would otherwise sail straight through and violate the constraint.
    ``isascii()`` is what actually restricts this to what the CHECK allows.
    """
    return "".join(
        ch for ch in raw.upper() if ch.isascii() and (ch.isalnum() or ch == "-")
    )


def _variant_sku(item_group_id: str, size: str, color: str) -> str:
    """Deterministic and constraint-shaped: ^[A-Z0-9][A-Z0-9-]*$.

    trg_variants_sku_immutable makes a bad SKU permanent — SKU is the join
    key Merchant Center, the Meta catalog and GA4 all key off of — so this
    must never emit anything outside the format, and two distinct inputs must
    never collapse onto the same output. Cleaning discards whatever the
    format forbids (non-ASCII such as an Arabic colour name, and punctuation
    like "." or "/"), and that discarding is exactly what can make two
    different inputs collide: "38.5" and "385" both clean to "385"; "M/L" and
    "ML" both clean to "ML". Whenever cleaning changes or empties a segment,
    a short stable hash of the ORIGINAL segment is appended so the discarded
    information still keeps it distinct.
    """
    segments = []
    for raw in (item_group_id, size, color):
        cleaned = _clean_sku_segment(raw)
        if cleaned != raw.upper() or not cleaned:
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6].upper()
            cleaned = f"{cleaned}{digest}" if cleaned else digest
        segments.append(cleaned)

    sku = "-".join(segments).strip("-")
    if not sku or not sku[0].isascii() or not sku[0].isalnum():
        # Unreachable given the per-segment guarantees above, but the format
        # constraint must never be violated by an input shape we didn't
        # foresee, so fall back to a hash of the whole original tuple.
        sku = hashlib.sha256(
            "|".join((item_group_id, size, color)).encode("utf-8")
        ).hexdigest()[:16].upper()
    return sku


def _unique_sku(db: Session, candidate: str, taken: set[str]) -> str:
    """Disambiguate a SKU that collides with one already taken.

    ``taken`` covers earlier rows generated in this same call (which are only
    flushed, not yet committed, so a fresh query would not see them from
    another connection — but does see them here, same transaction); the query
    covers every other product's variants, since UNIQUE(sku) is global, not
    per-product. trg_variants_sku_immutable makes a collision here permanent,
    so a numeric suffix is appended rather than letting the insert fail.
    """
    sku = candidate
    n = 2
    while sku in taken or db.execute(
        select(ProductVariant.id).where(ProductVariant.sku == sku)
    ).first() is not None:
        sku = f"{candidate}-{n}"
        n += 1
    return sku


def generate_variants(db, actor, product_id: int, sizes, colors, defaults: dict):
    """Create the size x colour cross product, skipping combinations that exist.

    SKUs are generated because they are immutable once written
    (trg_variants_sku_immutable) — a typo would otherwise be permanent.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    # The same money guards update_variant applies, for the same reason: these
    # are CHECK constraints (ck_variants_price_non_negative,
    # ck_variants_sale_price_valid, ck_variants_stock_non_negative), so without
    # them a negative value surfaces as an unreadable 500 at flush. Both write
    # paths have to refuse the same values or the edit screen and the create
    # screen disagree about what a valid variant is.
    price = Decimal(str(defaults.get("price", "0")))
    if price < 0:
        raise HTTPException(status_code=400, detail="price cannot be negative")

    sale_price = defaults.get("sale_price")
    sale_price = Decimal(str(sale_price)) if sale_price is not None else None
    if sale_price is not None and sale_price < 0:
        raise HTTPException(status_code=400, detail="sale price cannot be negative")
    if sale_price is not None and sale_price > price:
        raise HTTPException(
            status_code=400, detail="sale price cannot exceed the price"
        )

    stock_quantity = int(defaults.get("stock_quantity", 0))
    if stock_quantity < 0:
        raise HTTPException(status_code=400, detail="stock cannot be negative")

    material = defaults.get("material")

    # uq_product_variants_combination is (product_id, size, color, material) —
    # keying the skip check on size/colour alone would silently drop a request
    # that only differs by material: no row, no error.
    existing = {
        (v.size, v.color, v.material)
        for v in db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product_id)
        ).scalars()
    }

    taken_skus: set[str] = set()
    created = []
    for size in sizes:
        for color in colors:
            if (size, color, material) in existing:
                continue
            candidate = _variant_sku(product.item_group_id, size, color)
            sku = _unique_sku(db, candidate, taken_skus)
            if len(sku) > _SKU_MAX_LENGTH:
                # Checked after disambiguation, because the "-2" suffix
                # _unique_sku may add counts against the same 64 characters.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "item group id is too long to generate SKUs from — "
                        f"'{size} / {color}' would need "
                        f"{len(sku)} characters and the column allows "
                        f"{_SKU_MAX_LENGTH}"
                    ),
                )
            taken_skus.add(sku)
            variant = ProductVariant(
                product_id=product_id,
                sku=sku,
                variant_title=f"{size} / {color}",
                size=size,
                size_system=defaults.get("size_system"),
                color=color,
                material=material,
                attributes={},
                price=price,
                sale_price=sale_price,
                currency="EGP",
                cost=None,  # COGS is admin-gated; set on the variant edit screen
                availability=defaults.get("availability", "in_stock"),
                stock_quantity=stock_quantity,
                merchant_eligible=True,
                is_active=True,
            )
            db.add(variant)
            created.append(variant)

    db.flush()

    if created and product.default_variant_id is None:
        product.default_variant_id = created[0].id
        db.flush()

    _invalidate(db, product_id)
    return created


def get_product_for_admin(db, product_id: int) -> dict:
    """Everything the editor needs, regardless of publish state.

    Three queries — the product, its translations, its variants — so the shape
    stays constant as a product gains variants.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    translations = [
        {
            "locale": t.locale,
            "title": t.title,
            "description": t.description,
            "slug": t.slug,
            "meta_description": t.meta_description,
            "is_published": t.is_published,
            "is_complete": t.is_complete,
        }
        for t in db.execute(
            select(ProductTranslation)
            .where(ProductTranslation.product_id == product_id)
            .order_by(ProductTranslation.locale)
        ).scalars()
    ]

    variants = [
        {
            "id": v.id,
            "sku": v.sku,
            "variant_title": v.variant_title,
            "size": v.size,
            "color": v.color,
            "price": v.price,
            "sale_price": v.sale_price,
            "stock_quantity": v.stock_quantity,
            "is_active": v.is_active,
        }
        for v in db.execute(
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.id)
        ).scalars()
    ]

    return {
        "id": product.id,
        "item_group_id": product.item_group_id,
        "slug": product.slug,
        "title": product.title,
        "brand": product.brand,
        "status": product.status.value if hasattr(product.status, "value") else product.status,
        "category_id": product.category_id,
        "translations": translations,
        "variants": variants,
    }


_EDITABLE_BASE_FIELDS = (
    "title", "description", "brand", "tags",
    "condition", "gender", "age_group",
)


def update_product(db, actor, product_id: int, payload: dict):
    """Edit base (non-translated) fields. Status changes go through publish/archive."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    if "slug" in payload and payload["slug"] != product.slug:
        slug = (payload["slug"] or "").strip().lower()
        if not _SLUG_RE.match(slug):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="base slug must be ASCII lowercase, digits and single hyphens",
            )
        if db.execute(
            select(Product.id).where(Product.slug == slug, Product.id != product_id)
        ).first():
            raise HTTPException(status_code=409, detail="slug already in use")
        product.slug = slug

    if "category_id" in payload:
        category = db.get(Category, payload["category_id"])
        if category is None or category.level != 2:
            raise HTTPException(
                status_code=400, detail="products attach to level-2 categories only"
            )
        product.category_id = category.id

    for field in _EDITABLE_BASE_FIELDS:
        if field in payload:
            setattr(product, field, payload[field])

    try:
        db.flush()
    except IntegrityError as exc:
        # The pre-check above handles the common case cheaply; this catches a
        # concurrent rename to the same slug landing between the pre-check and
        # this flush -- create_product has the identical pattern, for the
        # identical reason (uq_products_slug is not enforceable by a SELECT).
        db.rollback()
        raise _conflict(exc)
    _invalidate(db, product_id)
    return product


def archive_product(db, actor, product_id: int):
    """Retire a product without deleting it.

    fk_order_items_product_id is ON DELETE RESTRICT, so anything sold cannot be
    deleted at all — and deleting would orphan the history GA4, Merchant Center
    and the Meta catalog key on. Every language is unpublished so the storefront
    stops serving it in both locales.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    for tr in db.execute(
        select(ProductTranslation).where(ProductTranslation.product_id == product_id)
    ).scalars():
        tr.is_published = False

    product.status = "archived"
    db.flush()
    _invalidate(db, product_id)
    return product


_EDITABLE_VARIANT_FIELDS = (
    "variant_title", "gtin", "mpn", "material", "size_system",
    "availability", "stock_quantity", "weight_grams",
    "length_cm", "width_cm", "height_cm", "merchant_eligible", "is_active",
)


def update_variant(db, actor, variant_id: int, payload: dict):
    """Edit a variant. SKU is refused; COGS requires an admin.

    Controller ruling (cross-task correction): making ``is_active`` editable
    exposes a bug that was latent while nothing could deactivate a variant --
    publish_readiness's ``no_default_variant`` check only tested
    ``default_variant_id IS NOT NULL``, never whether that variant was still
    active. Deactivating a product's default variant is therefore reassigned
    to another active variant here, mirroring how publish_product already
    self-heals a cleared default_variant_id from the first active variant --
    the same self-healing idiom, just triggered from the other direction.
    Refused with 409 only when no other active variant remains, since setting
    default_variant_id to NULL on a product that may already be
    status='active' would violate ck_products_active_has_default_variant.
    """
    variant = db.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="variant not found")

    if "sku" in payload and payload["sku"] is not None and payload["sku"] != variant.sku:
        # trg_variants_sku_immutable would raise a restrict_violation. Refusing
        # here gives the operator a sentence instead of a database error. An
        # explicit ``null`` is not a request to change anything -- sku is
        # NOT NULL, so "clear it" cannot be what the caller meant -- so it is
        # read the same as the field being absent, not as a rejected change.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKU is immutable — Merchant Center and the Meta catalog key on it",
        )

    replacement_id = None
    deactivating = (
        "is_active" in payload and not payload["is_active"] and variant.is_active
    )
    if deactivating:
        product = db.get(Product, variant.product_id)
        if product is not None and product.default_variant_id == variant.id:
            replacement_id = db.execute(
                select(ProductVariant.id)
                .where(
                    ProductVariant.product_id == variant.product_id,
                    ProductVariant.id != variant.id,
                    ProductVariant.is_active.is_(True),
                )
                .order_by(ProductVariant.id)
            ).scalars().first()
            if replacement_id is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "cannot deactivate the only active variant while it is "
                        "the product's default — activate or add another "
                        "variant first"
                    ),
                )

    if "cost" in payload:
        # COGS feeds order_items.unit_cogs and therefore contribution_profit.
        # It is a money field, not a catalog field: catalog (2) may set price
        # and stock, but only admin (4) may set cost. The route stays gated at
        # LEVEL_CATALOG -- whether admin is required depends on which field
        # was sent, not on the endpoint.
        if set_access_level(actor) < LEVEL_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="COGS may only be set by an admin",
            )
        cost = payload["cost"]
        cost = Decimal(str(cost)) if cost is not None else None
        if cost is not None and cost < 0:
            # ck_variants_cost_non_negative would otherwise surface this as a
            # raw 500 at flush.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cost cannot be negative",
            )
        variant.cost = cost

    price = Decimal(str(payload["price"])) if "price" in payload else variant.price
    if price < 0:
        # ck_variants_price_non_negative, same reasoning as cost above.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="price cannot be negative",
        )
    if "sale_price" in payload:
        sale_price = payload["sale_price"]
        sale_price = Decimal(str(sale_price)) if sale_price is not None else None
    else:
        sale_price = variant.sale_price

    if sale_price is not None and sale_price > price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sale price cannot exceed the price",
        )

    stock = payload.get("stock_quantity")
    if stock is not None and int(stock) < 0:
        # ck_variants_stock_non_negative. stock_quantity is set blindly with the
        # rest of _EDITABLE_VARIANT_FIELDS below, so this is the only place it
        # can be refused before the flush. An explicit null is left to the
        # column's own NOT NULL to reject, as it is for every other field here.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stock cannot be negative",
        )

    variant.price = price
    variant.sale_price = sale_price

    for field in _EDITABLE_VARIANT_FIELDS:
        if field in payload:
            setattr(variant, field, payload[field])

    if replacement_id is not None:
        product.default_variant_id = replacement_id

    db.flush()
    _invalidate(db, variant.product_id)
    return variant


def publish_readiness(db: Session, product_id: int, locale: str) -> list[dict]:
    """What still blocks this language from publishing, as data.

    Mirrors the database CHECK constraints deliberately. The constraints remain
    the authority -- this exists so the operator sees a sentence instead of an
    IntegrityError.

    ``is_complete`` is not consulted here, and must never be: it is a generated
    column computed from description + meta_description only (it omits title),
    so it does not mean "publishable" -- ck_..._published_requires_content also
    requires title. Presence of every field in ``_PUBLISHABLE_FIELDS`` is
    checked directly instead.
    """
    blockers: list[dict] = []

    variant_count = db.execute(
        select(func.count()).select_from(ProductVariant).where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
    ).scalar_one()
    if variant_count == 0:
        blockers.append({
            "code": "no_variant",
            "message": "Add at least one variant before publishing.",
        })
    else:
        product = db.get(Product, product_id)
        if product is not None:
            # ck_products_active_has_default_variant forbids status='active'
            # while default_variant_id is NULL -- but a non-NULL id pointing at
            # a deactivated variant satisfies that CHECK while still leaving
            # the storefront with no sellable default, so IS NOT NULL alone is
            # not "ready". publish_product backfills a NULL id from the first
            # active variant before it ever reaches this check, and
            # update_variant refuses to deactivate a default without another
            # active variant to reassign to -- but this is re-derived from the
            # rows rather than trusted from either caller, so a standalone
            # readiness check still reports the true state regardless of how
            # default_variant_id got here.
            default_id = product.default_variant_id
            default_is_active = default_id is not None and db.execute(
                select(ProductVariant.id).where(
                    ProductVariant.id == default_id,
                    ProductVariant.is_active.is_(True),
                )
            ).first() is not None
            if not default_is_active:
                blockers.append({
                    "code": "no_default_variant",
                    "message": "Set a default variant before publishing.",
                })

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one_or_none()

    if tr is None:
        blockers.append({
            "code": "no_translation",
            "message": f"No {locale} content exists yet.",
        })
    else:
        missing = _missing_publishable_fields(tr)
        if missing:
            blockers.append({
                "code": "incomplete_translation",
                "message": (
                    f"{locale} needs: " + ", ".join(m.replace("_", " ") for m in missing)
                ),
            })

    return blockers


def publish_product(db: Session, actor, product_id: int, locale: str) -> ProductTranslation:
    """Publish one language, activating the product if it was still a draft.

    Backfills ``default_variant_id`` from the first active variant when it is
    unset, before checking readiness. generate_variants sets it once when the
    first variant is created, but nothing keeps it set afterward, and
    ck_products_active_has_default_variant forbids status='active' while it is
    NULL -- doing the backfill first means the normal path self-heals instead
    of bouncing the operator with a blocker that publishing was about to fix
    anyway.
    """
    product = db.get(Product, product_id)
    if product is not None and product.default_variant_id is None:
        first_active_id = db.execute(
            select(ProductVariant.id)
            .where(
                ProductVariant.product_id == product_id,
                ProductVariant.is_active.is_(True),
            )
            .order_by(ProductVariant.id)
        ).scalars().first()
        if first_active_id is not None:
            product.default_variant_id = first_active_id
            db.flush()

    blockers = publish_readiness(db, product_id, locale)
    if blockers:
        raise HTTPException(status_code=422, detail=blockers)

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one()

    tr.is_published = True
    # is_complete is GENERATED ALWAYS AS (...) STORED -- it is never assigned
    # here. It also omits title from its expression, so it would be wrong
    # even as a proxy for "publishable".
    if product.status != "active":
        product.status = "active"

    db.flush()
    db.refresh(tr)
    _invalidate(db, product_id)
    return tr
