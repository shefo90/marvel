"""Back-office writes for the category tree and the collections.

The operator could not create a category at all before this: the taxonomy was
seeded by hand-written SQL. These prove the structural rules the schema relies
on are enforced as readable errors rather than surfacing as IntegrityErrors.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.collection_products import CollectionProduct
from repositories.admin_catalog import create_product
from repositories.admin_taxonomy import (
    collection_product_ids,
    create_category,
    create_collection,
    list_category_tree_for_admin,
    list_collections_for_admin,
    set_collection_products,
    update_category,
    update_collection,
    upsert_category_translation,
    upsert_collection_translation,
)
from services import cache
from services.cache_invalidation import run_pending
from tests.test_admin_writes import _actor, _level2_category, _locale


def _tag() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture
def actor(db):
    _locale(db, "en")
    _locale(db, "ar")
    return _actor(db)


# --- categories ----------------------------------------------------------

def test_a_top_level_category_is_level_one(db, actor):
    tag = _tag()
    category = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{tag}"})

    assert category.level == 1
    assert category.parent_id is None


def test_a_child_of_a_level_one_category_is_level_two(db, actor):
    parent = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})

    child = create_category(db, actor, {
        "name": "Sandals", "slug": f"sandals-{_tag()}", "parent_id": parent.id,
    })

    assert child.level == 2
    assert child.parent_id == parent.id


def test_a_third_level_is_refused_with_a_readable_error(db, actor):
    """categories.parent_level is generated and backs a composite FK, so a
    three-level tree cannot be stored. Refusing here turns what would be a 500
    at flush into something the operator can act on."""
    parent = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})
    child = create_category(db, actor, {
        "name": "Sandals", "slug": f"sandals-{_tag()}", "parent_id": parent.id,
    })

    with pytest.raises(HTTPException) as exc:
        create_category(db, actor, {
            "name": "Flat Sandals", "slug": f"flat-{_tag()}", "parent_id": child.id,
        })

    assert exc.value.status_code == 422
    assert "level-1" in exc.value.detail


def test_an_unknown_parent_is_a_404(db, actor):
    with pytest.raises(HTTPException) as exc:
        create_category(db, actor, {
            "name": "Orphan", "slug": f"orphan-{_tag()}", "parent_id": 99_000_000,
        })

    assert exc.value.status_code == 404


def test_a_duplicate_slug_is_a_409_not_a_500(db, actor):
    slug = f"shoes-{_tag()}"
    create_category(db, actor, {"name": "Shoes", "slug": slug})

    with pytest.raises(HTTPException) as exc:
        create_category(db, actor, {"name": "Shoes Again", "slug": slug})

    assert exc.value.status_code == 409


def test_a_category_cannot_change_parent(db, actor):
    """Moving a category between levels would change products.category_level,
    which is generated and backs a composite FK -- every product in it would
    have to move too. Refusing beats cascading silently."""
    parent = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})
    other = create_category(db, actor, {"name": "Bags", "slug": f"bags-{_tag()}"})
    child = create_category(db, actor, {
        "name": "Sandals", "slug": f"sandals-{_tag()}", "parent_id": parent.id,
    })

    with pytest.raises(HTTPException) as exc:
        update_category(db, actor, child.id, {"parent_id": other.id})

    assert exc.value.status_code == 422


def test_the_admin_tree_keeps_inactive_categories_visible(db, actor):
    """The operator deactivated it; a category that vanishes from its own
    editor reads as deleted."""
    category = create_category(db, actor, {
        "name": "Retired", "slug": f"retired-{_tag()}", "is_active": False,
    })

    tree = list_category_tree_for_admin(db)

    assert category.id in {node["id"] for node in tree}
    assert next(n for n in tree if n["id"] == category.id)["is_active"] is False


def test_a_category_translation_is_created_then_updated(db, actor):
    category = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})
    slug = f"ahthiya-{_tag()}"

    upsert_category_translation(db, actor, category.id, "ar", {
        "title": "أحذية", "slug": slug, "description": "وصف",
        "meta_description": "قصير", "is_published": True,
    })
    upsert_category_translation(db, actor, category.id, "ar", {"title": "أحذية نسائية"})

    db.refresh(category)
    arabic = [tr for tr in category.translations if tr.locale == "ar"]
    assert len(arabic) == 1, "the second upsert created a second row"
    assert arabic[0].title == "أحذية نسائية"
    assert arabic[0].slug == slug, "an untouched slug should not be regenerated"


def test_a_translation_without_a_title_is_refused(db, actor):
    category = create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})

    with pytest.raises(HTTPException) as exc:
        upsert_category_translation(db, actor, category.id, "ar", {"description": "وصف"})

    assert exc.value.status_code == 422


# --- collections ---------------------------------------------------------

def test_a_collections_list_id_is_normalized_to_the_check_constraints_shape(db, actor):
    """ck_collections_list_id_format allows ^[a-z0-9_]+$ only, and this is
    section 5's item_list_id -- a bad one is a 500 at flush, or worse, a report
    that splits one list into two."""
    collection = create_collection(db, actor, {
        "name": "Summer Edit 2026!", "slug": f"summer-{_tag()}",
    })

    assert collection.list_id.replace("_", "").isalnum()
    assert collection.list_id == collection.list_id.lower()


def test_collection_membership_keeps_the_order_it_was_given(db, actor):
    """The order is the data: position drives section 5's index and the
    collection's own featured sort."""
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })
    cat = _level2_category(db)
    products = [
        create_product(db, actor, {
            "title": f"P{i}", "slug": f"p{i}-{_tag()}", "brand": "Pixi",
            "category_id": cat.id,
        })
        for i in range(3)
    ]
    ordered = [products[2].id, products[0].id, products[1].id]

    set_collection_products(db, actor, collection.id, ordered)

    assert collection_product_ids(db, collection.id) == ordered


def test_reordering_a_collection_does_not_collide_on_position(db, actor):
    """uq_collection_products_position is a live UNIQUE constraint, not
    deferred, so writing final positions directly collides with the rows still
    holding them. A parking pass avoids that -- on a high offset, because
    ck_collection_products_position forbids the negatives reorder_images uses."""
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })
    cat = _level2_category(db)
    products = [
        create_product(db, actor, {
            "title": f"P{i}", "slug": f"p{i}-{_tag()}", "brand": "Pixi",
            "category_id": cat.id,
        })
        for i in range(3)
    ]
    first = [p.id for p in products]
    set_collection_products(db, actor, collection.id, first)

    set_collection_products(db, actor, collection.id, list(reversed(first)))

    assert collection_product_ids(db, collection.id) == list(reversed(first))


def test_replacing_the_membership_drops_products_left_out(db, actor):
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })
    cat = _level2_category(db)
    keep = create_product(db, actor, {
        "title": "Keep", "slug": f"keep-{_tag()}", "brand": "Pixi", "category_id": cat.id,
    })
    drop = create_product(db, actor, {
        "title": "Drop", "slug": f"drop-{_tag()}", "brand": "Pixi", "category_id": cat.id,
    })
    set_collection_products(db, actor, collection.id, [keep.id, drop.id])

    set_collection_products(db, actor, collection.id, [keep.id])

    assert collection_product_ids(db, collection.id) == [keep.id]
    assert db.execute(
        select(CollectionProduct).where(
            CollectionProduct.collection_id == collection.id,
            CollectionProduct.product_id == drop.id,
        )
    ).scalar_one_or_none() is None


def test_a_duplicate_product_in_the_membership_is_collapsed(db, actor):
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })
    cat = _level2_category(db)
    product = create_product(db, actor, {
        "title": "One", "slug": f"one-{_tag()}", "brand": "Pixi", "category_id": cat.id,
    })

    set_collection_products(db, actor, collection.id, [product.id, product.id])

    assert collection_product_ids(db, collection.id) == [product.id]


def test_an_unknown_product_id_is_refused_before_anything_is_written(db, actor):
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })

    with pytest.raises(HTTPException) as exc:
        set_collection_products(db, actor, collection.id, [99_000_000])

    assert exc.value.status_code == 404
    assert collection_product_ids(db, collection.id) == []


def test_an_inactive_collection_still_appears_in_the_admin_list(db, actor):
    collection = create_collection(db, actor, {
        "name": "Retired", "slug": f"retired-{_tag()}", "is_active": False,
    })

    rows = list_collections_for_admin(db)

    assert collection.id in {row["id"] for row in rows}


def test_updating_a_collection_can_deactivate_it(db, actor):
    collection = create_collection(db, actor, {
        "name": "Edit", "slug": f"edit-{_tag()}",
    })

    update_collection(db, actor, collection.id, {"is_active": False})

    assert collection.is_active is False


# --- cache invalidation --------------------------------------------------

def test_a_taxonomy_write_does_not_invalidate_before_it_commits(db, actor):
    """Same rule as every other write path: dropping the cache inside the
    transaction lets a storefront read repopulate it from the pre-commit rows,
    and the menu is cached for six hours."""
    before = cache.namespace_version(cache.NS_CATEGORY)

    create_category(db, actor, {"name": "Shoes", "slug": f"shoes-{_tag()}"})

    assert cache.namespace_version(cache.NS_CATEGORY) == before, (
        "the category cache was dropped before the write committed"
    )
    run_pending(db)
    assert cache.namespace_version(cache.NS_CATEGORY) != before
