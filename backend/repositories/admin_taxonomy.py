"""Back-office writes for the category tree and the collections.

Reads live in ``repositories.taxonomy`` (storefront) and
``repositories.admin_categories`` (the product form's picker). This file is the
only place either structure is written.

**Nothing here deletes.** A category has products pointing at it and a
collection has an ``item_list_id`` stamped onto historic cart and order lines;
removing either would either be blocked by a foreign key or silently orphan the
attribution that section 5 exists to preserve. ``is_active`` is the operator's
switch, exactly as it is for promotions.

**Every write invalidates the whole taxonomy namespace, after the commit.**
Namespace-wide because a single edit changes the tree's shape -- a rename
changes a slug, deactivating a parent removes its children from the menu -- so
there is no one key to drop. After the commit because dropping it before leaves
a window in which a storefront read repopulates the cache from the pre-commit
rows and serves the old menu for the next six hours; see
``services.cache_invalidation``.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collection_products import CollectionProduct
from models.collection_translations import CollectionTranslation
from models.collections import Collection
from models.products import Product
from repositories.admin_slugs import normalize_translation_slug
from repositories.taxonomy import invalidate_taxonomy
from services.cache_invalidation import on_commit
from services.optimistic_lock import guard_unmodified


def _invalidate(db: Session) -> None:
    on_commit(db, invalidate_taxonomy)


def _conflict(exc: IntegrityError, field: str) -> HTTPException:
    """A UNIQUE violation is the operator reusing a slug, not a server fault."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{field} is already taken",
    )


def _slug(raw: str) -> str:
    slug = normalize_translation_slug(raw)
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="slug is empty once normalized",
        )
    return slug


def _list_id(raw: str) -> str:
    """``^[a-z0-9_]+$`` -- what ck_collections_list_id_format allows.

    Underscores, not hyphens, and never localized: this is section 5's
    ``item_list_id``, and the Arabic and English pages for one category must
    report the same value or a single shop's traffic splits in two.
    """
    cleaned = "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch == "_")) else "_"
        for ch in raw.lower()
    ).strip("_")
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="list_id is empty once normalized",
        )
    return cleaned


# --- categories ----------------------------------------------------------

def list_category_tree_for_admin(db: Session) -> list[dict]:
    """The whole tree, inactive rows included.

    Inactive is shown and flagged rather than hidden: the operator is the one
    who deactivated it, and a category that vanishes from its own editor looks
    deleted.
    """
    rows = db.execute(
        select(Category).order_by(Category.level, Category.position, Category.name)
    ).scalars().all()

    counts = dict(
        db.execute(
            select(Product.category_id, func.count())
            .where(Product.category_id.is_not(None))
            .group_by(Product.category_id)
        ).all()
    )

    def payload(category: Category) -> dict:
        return {
            "id": category.id,
            "parent_id": category.parent_id,
            "level": category.level,
            "name": category.name,
            "slug": category.slug,
            "list_id": category.list_id,
            "position": category.position,
            "is_active": category.is_active,
            "product_count": counts.get(category.id, 0),
            # The version the edit form is built from; sent back as
            # expected_updated_at so a stale save is refused rather than
            # silently overwriting another operator.
            "updated_at": category.updated_at,
            "translations": [
                {
                    "locale": tr.locale,
                    "title": tr.title,
                    "slug": tr.slug,
                    "description": tr.description,
                    "meta_description": tr.meta_description,
                    "is_published": tr.is_published,
                }
                for tr in category.translations
            ],
            "children": [],
        }

    payloads = {c.id: payload(c) for c in rows}
    tree = []
    for category in rows:
        node = payloads[category.id]
        if category.parent_id is None:
            tree.append(node)
        elif category.parent_id in payloads:
            payloads[category.parent_id]["children"].append(node)
    return tree


def create_category(db: Session, actor, payload: dict) -> Category:
    """Create a level-1 or level-2 category.

    The level is derived from ``parent_id`` rather than accepted from the
    caller. ``categories.parent_level`` is a generated column with a composite
    self-FK, so an inconsistent pair is an IntegrityError at flush -- deriving
    it means the operator cannot produce one.
    """
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        parent = db.get(Category, parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="parent category not found")
        if parent.level != 1:
            # The tree is two deep by construction; a third level cannot be
            # stored, so refusing here is clearer than an IntegrityError.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="only a level-1 category may be a parent",
            )

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    # list_id defaults from the SLUG, not the name. Two categories may legibly
    # share a name ("Sandals" under Shoes and under Kids) but never a slug, and
    # list_id is UNIQUE -- deriving it from the name makes the second one a 409
    # the operator cannot explain.
    slug = _slug(payload.get("slug") or name)
    category = Category(
        parent_id=parent_id,
        level=2 if parent_id else 1,
        name=name,
        slug=slug,
        list_id=_list_id(payload.get("list_id") or f"cat_{slug}"),
        description=payload.get("description"),
        google_product_category=payload.get("google_product_category"),
        position=payload.get("position") or 0,
        is_active=payload.get("is_active", True),
    )
    db.add(category)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug or list_id") from exc
    _invalidate(db)
    return category


def update_category(db: Session, actor, category_id: int, payload: dict) -> Category:
    """Edit a category. The parent is not editable -- see below."""
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")

    guard_unmodified(category, payload, what="category")

    if "parent_id" in payload and payload["parent_id"] != category.parent_id:
        # Moving a category between levels would change products.category_level,
        # which is generated and backs a composite FK -- every product in it
        # would have to move too. The operator's real intent is almost always a
        # new category, so this refuses rather than cascading silently.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a category cannot change parent; create a new one and move its products",
        )

    for field in ("name", "description", "google_product_category", "position"):
        if field in payload and payload[field] is not None:
            setattr(category, field, payload[field])
    if payload.get("slug"):
        category.slug = _slug(payload["slug"])
    if payload.get("list_id"):
        category.list_id = _list_id(payload["list_id"])
    if "is_active" in payload:
        category.is_active = bool(payload["is_active"])

    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug or list_id") from exc
    _invalidate(db)
    return category


def upsert_category_translation(
    db: Session, actor, category_id: int, locale: str, payload: dict
) -> CategoryTranslation:
    """One locale's name, slug and SEO copy for a category."""
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="category not found")

    tr = db.execute(
        select(CategoryTranslation).where(
            CategoryTranslation.category_id == category_id,
            CategoryTranslation.locale == locale,
        )
    ).scalar_one_or_none()
    is_new = tr is None
    if is_new:
        tr = CategoryTranslation(category_id=category_id, locale=locale)
        db.add(tr)

    for field in ("title", "description", "seo_title", "meta_description"):
        if field in payload:
            setattr(tr, field, payload[field])
    if payload.get("slug"):
        tr.slug = _slug(payload["slug"])
    elif is_new:
        tr.slug = _slug(payload.get("title") or category.slug)
    if not tr.title:
        raise HTTPException(status_code=422, detail="title is required")
    if "is_published" in payload:
        tr.is_published = bool(payload["is_published"])

    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug") from exc
    _invalidate(db)
    return tr


# --- collections ---------------------------------------------------------

def list_collections_for_admin(db: Session) -> list[dict]:
    rows = db.execute(
        select(Collection).order_by(Collection.position, Collection.name)
    ).scalars().all()
    counts = dict(
        db.execute(
            select(CollectionProduct.collection_id, func.count())
            .group_by(CollectionProduct.collection_id)
        ).all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "list_id": c.list_id,
            "description": c.description,
            "position": c.position,
            "is_active": c.is_active,
            "product_count": counts.get(c.id, 0),
            "updated_at": c.updated_at,
            "translations": [
                {
                    "locale": tr.locale,
                    "title": tr.title,
                    "slug": tr.slug,
                    "description": tr.description,
                    "meta_description": tr.meta_description,
                    "is_published": tr.is_published,
                }
                for tr in c.translations
            ],
        }
        for c in rows
    ]


def create_collection(db: Session, actor, payload: dict) -> Collection:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    slug = _slug(payload.get("slug") or name)
    collection = Collection(
        name=name,
        slug=slug,
        list_id=_list_id(payload.get("list_id") or slug),
        description=payload.get("description"),
        position=payload.get("position") or 0,
        is_active=payload.get("is_active", True),
    )
    db.add(collection)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug or list_id") from exc
    _invalidate(db)
    return collection


def update_collection(db: Session, actor, collection_id: int, payload: dict) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    guard_unmodified(collection, payload, what="collection")

    for field in ("name", "description", "position"):
        if field in payload and payload[field] is not None:
            setattr(collection, field, payload[field])
    if payload.get("slug"):
        collection.slug = _slug(payload["slug"])
    if payload.get("list_id"):
        collection.list_id = _list_id(payload["list_id"])
    if "is_active" in payload:
        collection.is_active = bool(payload["is_active"])

    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug or list_id") from exc
    _invalidate(db)
    return collection


def upsert_collection_translation(
    db: Session, actor, collection_id: int, locale: str, payload: dict
) -> CollectionTranslation:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    tr = db.execute(
        select(CollectionTranslation).where(
            CollectionTranslation.collection_id == collection_id,
            CollectionTranslation.locale == locale,
        )
    ).scalar_one_or_none()
    is_new = tr is None
    if is_new:
        tr = CollectionTranslation(collection_id=collection_id, locale=locale)
        db.add(tr)

    for field in ("title", "description", "seo_title", "meta_description"):
        if field in payload:
            setattr(tr, field, payload[field])
    if payload.get("slug"):
        tr.slug = _slug(payload["slug"])
    elif is_new:
        tr.slug = _slug(payload.get("title") or collection.slug)
    if not tr.title:
        raise HTTPException(status_code=422, detail="title is required")
    if "is_published" in payload:
        tr.is_published = bool(payload["is_published"])

    try:
        db.flush()
    except IntegrityError as exc:
        raise _conflict(exc, "slug") from exc
    _invalidate(db)
    return tr


# Where reordering parks rows mid-update. Above any hand-curated collection,
# and positive because ck_collection_products_position forbids negatives.
PARKING_OFFSET = 1_000_000


def set_collection_products(
    db: Session, actor, collection_id: int, product_ids: list[int]
) -> list[int]:
    """Replace the membership, in the order given.

    The order *is* the data: ``position`` drives section 5's ``index`` on
    ``view_item_list``, and "featured" sorting inside a collection is this
    order. So this takes the full list rather than an add/remove pair -- a
    partial update cannot express a reordering.

    Written in two passes for the same reason ``reorder_images`` is:
    uq_collection_products_position is a live UNIQUE constraint, not deferred,
    so writing the final positions directly collides with the rows still
    holding them. The first pass parks everything out of the way.

    It parks on a high offset rather than on negatives, which is where this
    differs from ``reorder_images``: ck_collection_products_position requires
    ``position >= 0``, so the negative trick that works for images is rejected
    here. PARKING_OFFSET is far above any membership a person would curate by
    hand.
    """
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="collection not found")

    ordered = list(dict.fromkeys(product_ids))  # de-duplicate, keep first position
    if ordered:
        known = set(
            db.execute(
                select(Product.id).where(Product.id.in_(ordered))
            ).scalars()
        )
        missing = [pid for pid in ordered if pid not in known]
        if missing:
            raise HTTPException(
                status_code=404, detail=f"unknown product ids: {missing}"
            )

    existing = {
        link.product_id: link
        for link in db.execute(
            select(CollectionProduct).where(
                CollectionProduct.collection_id == collection_id
            )
        ).scalars()
    }

    for index, link in enumerate(existing.values()):
        link.position = PARKING_OFFSET + index
    db.flush()

    for position, product_id in enumerate(ordered):
        link = existing.get(product_id)
        if link is None:
            db.add(CollectionProduct(
                collection_id=collection_id, product_id=product_id, position=position
            ))
        else:
            link.position = position
    for product_id, link in existing.items():
        if product_id not in ordered:
            db.delete(link)
    db.flush()

    _invalidate(db)
    return ordered


def collection_product_ids(db: Session, collection_id: int) -> list[int]:
    return list(
        db.execute(
            select(CollectionProduct.product_id)
            .where(CollectionProduct.collection_id == collection_id)
            .order_by(CollectionProduct.position)
        ).scalars()
    )
