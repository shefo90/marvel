"""Repository-level admin catalog writes, on the rolled-back session."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.categories import Category
from models.locales import Locale
from models.product_translations import ProductTranslation
from models.url_redirects import UrlRedirect
from models.users import User
from repositories.admin_catalog import create_product, upsert_translation
from services import cache


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


def test_invalid_slug_format_is_rejected_with_400(db):
    cat = _level2_category(db)
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), {
            "title": "X", "slug": "Not A Valid Slug!", "brand": "Pixi",
            "category_id": cat.id,
        })
    assert exc.value.status_code == 400


def test_nonexistent_category_is_rejected_with_400(db):
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), {
            "title": "X", "slug": "no-such-category", "brand": "Pixi",
            "category_id": 999_999_999,
        })
    assert exc.value.status_code == 400


def test_missing_category_id_is_rejected_with_400(db):
    """Raw ``payload["category_id"]`` indexing would raise KeyError -> 500 here."""
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), {
            "title": "X", "slug": "missing-category-id", "brand": "Pixi",
        })
    assert exc.value.status_code == 400


def test_product_without_explicit_gender_gets_the_column_default(db):
    """An explicit ``gender=None`` would write NULL over the server_default —
    this is a women's footwear store, and gender is required on every apparel
    offer for the Merchant Center feed (requirements section 8)."""
    cat = _level2_category(db)
    product = create_product(db, _actor(db), {
        "title": "Suede Sandal", "slug": "gender-default-check",
        "brand": "Pixi", "category_id": cat.id,
    })
    assert product.gender is not None
    assert product.gender == "female"


def _locale(db, code: str) -> None:
    if db.get(Locale, code) is None:
        db.add(Locale(
            code=code, hreflang=code, name_native=code,
            text_direction="rtl" if code == "ar" else "ltr",
            is_default=(code == "en"), is_active=True, sort_order=1,
        ))
        db.flush()


def test_translation_is_created_unpublished_and_incomplete(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    assert tr.is_published is False
    assert tr.is_complete is False   # description + meta_description missing


def test_translation_becomes_complete_when_all_publishable_fields_are_present(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-2", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل",
        "description": "وصف",
        "meta_description": "وصف قصير",
    })

    assert tr.is_complete is True


def test_slug_defaults_to_the_normalized_title(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-3", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {"title": "صندل جلد"})

    assert tr.slug == "صندل-جلد"


def test_renaming_a_published_slug_writes_a_301(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-4", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل",
        "description": "وصف",
        "meta_description": "قصير",
        "slug": "صندل",
        "is_published": True,
    })

    upsert_translation(db, actor, p.id, "ar", {"slug": "صندل-جديد"})

    redirect = db.execute(
        select(UrlRedirect).where(UrlRedirect.entity_id == p.id)
    ).scalar_one()
    assert redirect.from_path == "/ar/products/صندل"
    assert redirect.status_code == 301


def test_renaming_an_unpublished_slug_writes_no_redirect(db):
    """Nothing has indexed a draft, so a redirect would be noise."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-5", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "slug": "صندل-قديم",
    })

    upsert_translation(db, actor, p.id, "ar", {"slug": "صندل-اخر"})

    assert db.execute(
        select(UrlRedirect).where(UrlRedirect.entity_id == p.id)
    ).first() is None


def test_renaming_a_slug_drops_the_old_slugs_cache_entry(db):
    """_invalidate's docstring claims it drops every cached copy. Before the
    fix it only rebuilt keys from the CURRENT rows, so a renamed locale's OLD
    slug -- what get_product_by_slug is keyed on -- kept serving a stale hit
    until TTL_PRICING (60s) expired on its own."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-6", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل", "slug": "صندل-قديم-2"})

    old_key = cache.key(cache.NS_PRODUCT, "ar", "صندل-قديم-2")
    cache.set(old_key, {"stale": True})
    assert cache.get(old_key) == {"stale": True}

    upsert_translation(db, actor, p.id, "ar", {"slug": "صندل-جديد-2"})

    assert cache.get(old_key) is None


def test_publishing_an_incomplete_translation_is_rejected_with_422(db):
    """The published-requires-content CHECK would otherwise surface as a raw
    IntegrityError -> 500 at flush; the operator needs a readable error."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-8", "brand": "Pixi", "category_id": cat.id,
    })

    with pytest.raises(HTTPException) as exc:
        upsert_translation(db, actor, p.id, "ar", {
            "title": "صندل", "is_published": True,
        })
    assert exc.value.status_code == 422

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == p.id, ProductTranslation.locale == "ar",
        )
    ).scalar_one_or_none()
    assert tr is None or tr.is_published is False
