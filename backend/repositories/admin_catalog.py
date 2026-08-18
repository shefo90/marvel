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

import re
import secrets

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.categories import Category
from models.product_images import ProductImage
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from repositories.admin_slugs import normalize_translation_slug, record_slug_change
from services import cache

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# ck_product_translations_published_requires_content
_PUBLISHABLE_FIELDS = ("title", "description", "meta_description")


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
    except IntegrityError:
        # The pre-check above handles the common case cheaply; this catches a
        # concurrent insert of the same slug that lands between the pre-check
        # and this flush (repositories/register.py has the same pattern for
        # uq_users_email).
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slug already in use"
        )
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

    if "is_published" in payload:
        tr.is_published = bool(payload["is_published"])

    db.flush()
    db.refresh(tr)

    # A draft has never been indexed, so a redirect from it would be noise.
    if was_published and old_slug and old_slug != tr.slug:
        record_slug_change(
            db, locale=locale, old_slug=old_slug,
            product_id=product_id, actor_id=actor.id,
        )
        db.flush()

    _invalidate(db, product_id)
    return tr


def _invalidate(db: Session, product_id: int) -> None:
    """Drop every cached copy of this product, in every locale it has.

    invalidate_product's docstring is explicit that a missing locale leaves that
    locale serving stale content, so the map is read from the rows rather than
    assumed.
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
