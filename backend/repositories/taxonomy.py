"""The browsable shape of the catalog: the category tree and the collections.

Separate from ``repositories.product`` because these answer a different
question. ``product`` answers "what is in this list"; this answers "what lists
exist" — the navigation menu, the breadcrumb, and the copy at the head of a
category page. They cache differently too: a listing carries price and stock and
so expires in a minute, while a category's name and description change only when
an operator edits them.

**Two levels, and the database enforces it.** ``categories.parent_level`` is a
generated column and the self-FK is composite, so a three-level tree is not
representable. The tree returned here is therefore always exactly two deep and
the frontend can rely on that instead of recursing.

**A category needs a published translation to be navigable, but not a complete
one.** ``is_complete`` is generated from description *and* meta_description,
which are SEO fields a menu entry does not need; requiring it would empty the
navigation the moment someone published a category without writing a meta
description. Product listings are stricter, because a product page that thin
should not be indexed at all.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collection_translations import CollectionTranslation
from models.collections import Collection
from services import cache


def _navigable(stmt, translation, locale: str):
    """Published in this locale. See the module docstring on is_complete."""
    return stmt.where(
        translation.locale == locale,
        translation.is_published.is_(True),
    )


def _category_payload(category: Category, tr: CategoryTranslation) -> dict:
    return {
        "id": category.id,
        "slug": tr.slug,
        "title": tr.title,
        "description": tr.description,
        "level": category.level,
        # Section 5's item_list_id. The same string must reach the dataLayer,
        # the cart line and the order line unchanged, so it is never localized.
        "list_id": category.list_id,
        "seo_title": tr.seo_title or tr.title,
        "meta_description": tr.meta_description,
        "is_indexable": bool(tr.robots_index and category.is_indexable),
        "canonical_url": tr.canonical_override or f"/{tr.locale}/c/{tr.slug}",
    }


def category_tree(db: Session, locale: str) -> list[dict]:
    """The navigation menu: level-1 categories, each with its level-2 children.

    One query, not one per parent. The tree is small, but this runs on every
    server-rendered page in both locales, so an N+1 here is an N+1 everywhere.
    """

    def load() -> list[dict]:
        rows = db.execute(
            _navigable(
                select(Category, CategoryTranslation).join(
                    CategoryTranslation,
                    CategoryTranslation.category_id == Category.id,
                ),
                CategoryTranslation,
                locale,
            )
            .where(Category.is_active.is_(True))
            .order_by(Category.level, Category.position, CategoryTranslation.title)
        ).all()

        payloads: dict[int, dict] = {}
        roots: list[dict] = []
        for category, tr in rows:
            payload = _category_payload(category, tr)
            payload["children"] = []
            payloads[category.id] = payload
            if category.parent_id is None:
                roots.append(payload)

        for category, _ in rows:
            if category.parent_id is not None:
                parent = payloads.get(category.parent_id)
                # A child whose parent is inactive or untranslated is dropped
                # rather than promoted: a level-2 category rendered at the top
                # of the menu would sit beside Shoes and Bags as if it were
                # their peer.
                if parent is not None:
                    parent["children"].append(payloads[category.id])

        return roots

    return cache.get_or_set(
        cache.key(cache.NS_CATEGORY, locale, "tree"), load, ttl=cache.TTL_CONTENT
    )


def get_category(db: Session, locale: str, slug: str) -> dict | None:
    """One category, with its parent for the breadcrumb. None when unknown."""

    def load() -> dict | None:
        row = db.execute(
            _navigable(
                select(Category, CategoryTranslation).join(
                    CategoryTranslation,
                    CategoryTranslation.category_id == Category.id,
                ),
                CategoryTranslation,
                locale,
            ).where(
                CategoryTranslation.slug == slug, Category.is_active.is_(True)
            )
        ).one_or_none()
        if row is None:
            return None

        category, tr = row
        payload = _category_payload(category, tr)
        payload["parent"] = None
        if category.parent_id is not None:
            parent = db.execute(
                _navigable(
                    select(Category, CategoryTranslation).join(
                        CategoryTranslation,
                        CategoryTranslation.category_id == Category.id,
                    ),
                    CategoryTranslation,
                    locale,
                ).where(Category.id == category.parent_id)
            ).one_or_none()
            if parent is not None:
                payload["parent"] = _category_payload(*parent)
        return payload

    return cache.get_or_set(
        cache.key(cache.NS_CATEGORY, locale, slug), load, ttl=cache.TTL_CONTENT
    )


def _collection_payload(collection: Collection, tr: CollectionTranslation) -> dict:
    return {
        "id": collection.id,
        "slug": tr.slug,
        "title": tr.title,
        "description": tr.description,
        "list_id": collection.list_id,
        "seo_title": tr.seo_title or tr.title,
        "meta_description": tr.meta_description,
        "is_indexable": bool(tr.robots_index and collection.is_indexable),
        "canonical_url": tr.canonical_override or f"/{tr.locale}/edit/{tr.slug}",
    }


def list_collections(db: Session, locale: str) -> list[dict]:
    """Active collections in merchandising order.

    Collections cut across the category tree — "Summer Edit" holds sandals and
    bags alike — so they are a flat list, never nested under a category.
    """

    def load() -> list[dict]:
        rows = db.execute(
            _navigable(
                select(Collection, CollectionTranslation).join(
                    CollectionTranslation,
                    CollectionTranslation.collection_id == Collection.id,
                ),
                CollectionTranslation,
                locale,
            )
            .where(Collection.is_active.is_(True))
            .order_by(Collection.position, CollectionTranslation.title)
        ).all()
        return [_collection_payload(c, tr) for c, tr in rows]

    return cache.get_or_set(
        cache.key(cache.NS_COLLECTION, locale, "all"), load, ttl=cache.TTL_CONTENT
    )


def get_collection(db: Session, locale: str, slug: str) -> dict | None:
    def load() -> dict | None:
        row = db.execute(
            _navigable(
                select(Collection, CollectionTranslation).join(
                    CollectionTranslation,
                    CollectionTranslation.collection_id == Collection.id,
                ),
                CollectionTranslation,
                locale,
            ).where(
                CollectionTranslation.slug == slug, Collection.is_active.is_(True)
            )
        ).one_or_none()
        return _collection_payload(*row) if row is not None else None

    return cache.get_or_set(
        cache.key(cache.NS_COLLECTION, locale, slug), load, ttl=cache.TTL_CONTENT
    )


def invalidate_taxonomy() -> None:
    """Drop every cached menu, category page and collection page.

    Namespace-wide rather than targeted, and deliberately so: a category edit
    can change the tree's shape (a rename changes a slug, deactivating a parent
    removes its children from the menu), so there is no single key to drop.
    These namespaces hold a handful of keys per locale, and the versioned scheme
    makes the whole sweep one O(1) write.

    Admin category and collection writes MUST call this. Nothing else does --
    ``TTL_CONTENT`` is six hours, which is a long time to serve a menu that no
    longer matches the shop.
    """
    cache.invalidate_namespace(cache.NS_CATEGORY)
    cache.invalidate_namespace(cache.NS_COLLECTION)
    # Listings embed the category and collection names they were reached by.
    cache.invalidate_namespace(cache.NS_LISTING)
