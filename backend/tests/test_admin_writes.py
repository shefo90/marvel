"""Repository-level admin catalog writes, on the rolled-back session."""

import pytest
from fastapi import HTTPException

from models.categories import Category
from models.users import User
from repositories.admin_catalog import create_product


def _level2_category(db) -> Category:
    """Products attach only to level-2 categories (category_level is generated)."""
    top = Category(
        parent_id=None, level=1, name="W1", slug="w-plan-top",
        list_id="w_plan_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="W2", slug="w-plan-child",
        list_id="w_plan_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _actor(db) -> User:
    """Reuse the row already in the session, if any — ``users`` has a UNIQUE
    index on ``lower(email)`` and several tests need an actor more than once
    within the same rolled-back session."""
    existing = (
        db.query(User).filter(User.email == "plan-writer@example.com").first()
    )
    if existing is not None:
        return existing
    user = User(
        email="plan-writer@example.com", password_hash="x",
        full_name="Writer", role="catalog", is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def test_new_product_starts_as_a_draft(db):
    cat = _level2_category(db)
    product = create_product(db, _actor(db), {
        "title": "Suede Sandal", "slug": "suede-sandal",
        "brand": "Pixi", "category_id": cat.id,
    })
    assert product.status == "draft"


def test_item_group_id_is_generated_when_not_supplied(db):
    """It is Merchant's variant-grouping key and UNIQUE — never typed by hand."""
    cat = _level2_category(db)
    product = create_product(db, _actor(db), {
        "title": "Suede Sandal", "slug": "suede-sandal-2",
        "brand": "Pixi", "category_id": cat.id,
    })
    assert product.item_group_id
    assert product.item_group_id == product.item_group_id.upper()


def test_duplicate_slug_is_rejected_with_409(db):
    cat = _level2_category(db)
    base = {"title": "A", "brand": "Pixi", "category_id": cat.id, "slug": "dup-slug"}
    create_product(db, _actor(db), base)
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), dict(base, title="B"))
    assert exc.value.status_code == 409


def test_level_1_category_is_rejected(db):
    """The composite FK to categories(id, level) would fail with a raw 500."""
    top = Category(
        parent_id=None, level=1, name="T", slug="w-plan-only-top",
        list_id="w_plan_only_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), {
            "title": "X", "slug": "x-prod", "brand": "Pixi", "category_id": top.id,
        })
    assert exc.value.status_code == 400
