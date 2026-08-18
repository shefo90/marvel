"""Repository-level admin catalog writes, on the rolled-back session."""

import re
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.categories import Category
from models.locales import Locale
from models.product_translations import ProductTranslation
from models.products import Product
from models.url_redirects import UrlRedirect
from models.users import User
from repositories.admin_catalog import (
    archive_product,
    create_product,
    generate_variants,
    get_product_for_admin,
    publish_product,
    publish_readiness,
    update_product,
    update_variant,
    upsert_translation,
)
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


def test_matrix_creates_one_variant_per_size_and_colour(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(
        db, actor, p.id, ["38", "39"], ["black", "tan"], {"price": "500.00"}
    )

    assert len(variants) == 4


def test_generated_skus_match_the_format_constraint(db):
    import re
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-2", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    assert re.match(r"^[A-Z0-9][A-Z0-9-]*$", variants[0].sku)


def test_first_generated_variant_becomes_the_default(db):
    """ck_products_active_has_default_variant blocks publishing without one."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-3", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    db.refresh(p)
    assert p.default_variant_id == variants[0].id


def test_regenerating_an_existing_combination_is_skipped_not_duplicated(db):
    """UNIQUE(product_id, size, color, material) would otherwise raise."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-4", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    second = generate_variants(
        db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"}
    )

    assert len(second) == 1
    assert second[0].size == "39"


def test_sale_price_above_price_is_rejected(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-5", "brand": "Pixi", "category_id": cat.id,
    })

    with pytest.raises(HTTPException) as exc:
        generate_variants(db, actor, p.id, ["38"], ["black"],
                          {"price": "500.00", "sale_price": "600.00"})

    assert exc.value.status_code == 400


_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]*$")

# "black" in Arabic. Written as \uXXXX escapes rather than a literal: the
# console this suite runs under is cp1252 and printing the literal raises
# UnicodeEncodeError on a failed-assertion traceback.
_ARABIC_BLACK = "أسود"


def test_non_ascii_colour_produces_a_check_valid_sku(db):
    """str.isalnum()/str.upper() are Unicode-aware, so an Arabic colour name
    would otherwise sail straight through _variant_sku and violate
    ck_variants_sku_format instead of being cleaned out."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-6", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(
        db, actor, p.id, ["38"], [_ARABIC_BLACK], {"price": "500.00"}
    )

    assert len(variants) == 1
    assert _SKU_RE.match(variants[0].sku)


def test_dotted_and_undotted_sizes_produce_different_skus(db):
    """"38.5" and "385" both clean to "385" -- stripping punctuation must not
    let two distinct sizes collide onto the same immutable SKU."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-7", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(
        db, actor, p.id, ["38.5", "385"], ["black"], {"price": "500.00"}
    )

    assert len(variants) == 2
    by_size = {v.size: v.sku for v in variants}
    for sku in by_size.values():
        assert _SKU_RE.match(sku)
    assert by_size["38.5"] != by_size["385"]


def test_item_group_ids_differing_only_by_punctuation_produce_different_skus(db):
    """item_group_id has no format validation (unlike slug), so "ABC-123" and
    "ABC!123" are both valid and distinct, yet strip to the same "ABC123" --
    generating the same size/colour on both products must not collide on the
    global UNIQUE(sku)."""
    cat, actor = _level2_category(db), _actor(db)
    p1 = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-8", "brand": "Pixi", "category_id": cat.id,
        "item_group_id": "ABC-123",
    })
    p2 = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-9", "brand": "Pixi", "category_id": cat.id,
        "item_group_id": "ABC!123",
    })

    v1 = generate_variants(db, actor, p1.id, ["38"], ["black"], {"price": "500.00"})
    v2 = generate_variants(db, actor, p2.id, ["38"], ["black"], {"price": "500.00"})

    assert _SKU_RE.match(v1[0].sku)
    assert _SKU_RE.match(v2[0].sku)
    assert v1[0].sku != v2[0].sku


def test_same_size_and_colour_with_different_material_creates_a_row(db):
    """uq_product_variants_combination is (product_id, size, color, material).
    Keying the skip check on size/colour alone would silently drop this
    second call -- no row, no error -- instead of creating the new material."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-10", "brand": "Pixi", "category_id": cat.id,
    })
    first = generate_variants(
        db, actor, p.id, ["38"], ["black"], {"price": "500.00", "material": "leather"}
    )

    second = generate_variants(
        db, actor, p.id, ["38"], ["black"], {"price": "500.00", "material": "suede"}
    )

    assert len(second) == 1
    assert second[0].material == "suede"
    # Same size/colour/item_group_id as `first` -- the SKU generator alone
    # would propose the same candidate SKU for both; uniqueness must still
    # hold against the global UNIQUE(sku) constraint.
    assert second[0].sku != first[0].sku
    assert _SKU_RE.match(second[0].sku)


def test_readiness_reports_a_missing_variant(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-1", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف",
        "meta_description": "قصير",
    })

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "no_variant" in codes


def test_readiness_reports_missing_translation_content(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-2", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "incomplete_translation" in codes


def test_a_ready_product_publishes_and_goes_active(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-3", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف",
        "meta_description": "قصير",
    })

    tr = publish_product(db, actor, p.id, "ar")

    db.refresh(p)
    assert tr.is_published is True
    assert p.status == "active"


def test_publishing_an_unready_product_raises_422_with_blockers(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-4", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    with pytest.raises(HTTPException) as exc:
        publish_product(db, actor, p.id, "ar")

    assert exc.value.status_code == 422
    assert isinstance(exc.value.detail, list)
    assert {b["code"] for b in exc.value.detail} >= {"no_variant", "incomplete_translation"}


def test_publishing_one_language_leaves_the_other_unpublished(db):
    """Per-language publishing is the whole point of the draft flow."""
    _locale(db, "ar")
    _locale(db, "en")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-5", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف",
        "meta_description": "قصير",
    })
    upsert_translation(db, actor, p.id, "en", {"title": "Sandal"})

    publish_product(db, actor, p.id, "ar")

    en = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == p.id, ProductTranslation.locale == "en"
        )
    ).scalar_one()
    assert en.is_published is False


def test_readiness_reports_no_default_variant_when_it_was_cleared(db):
    """ck_products_active_has_default_variant forbids status='active' while
    default_variant_id is NULL. generate_variants sets it once, but nothing
    stops it being cleared afterward (e.g. the chosen variant deactivated) --
    readiness must surface that as data, not let publish crash into an
    IntegrityError."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-6", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    p.default_variant_id = None
    db.flush()

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "no_default_variant" in codes


def test_publish_backfills_a_cleared_default_variant(db):
    """publish_product self-heals a cleared default_variant_id from the first
    active variant rather than blocking the operator or raising a raw
    IntegrityError at flush."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-7", "brand": "Pixi", "category_id": cat.id,
    })
    variants = generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    p.default_variant_id = None
    db.flush()
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف",
        "meta_description": "قصير",
    })

    tr = publish_product(db, actor, p.id, "ar")

    db.refresh(p)
    assert p.default_variant_id == variants[0].id
    assert p.status == "active"
    assert tr.is_published is True


def test_editor_load_returns_every_locale_including_unpublished(db):
    _locale(db, "ar")
    _locale(db, "en")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "load-1", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})
    upsert_translation(db, actor, p.id, "en", {"title": "Sandal"})

    loaded = get_product_for_admin(db, p.id)

    assert {t["locale"] for t in loaded["translations"]} == {"ar", "en"}
    assert all(t["is_published"] is False for t in loaded["translations"])


def test_editor_load_includes_variants(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "load-2", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"})

    loaded = get_product_for_admin(db, p.id)

    assert len(loaded["variants"]) == 2


def test_editor_load_of_a_missing_product_is_404(db):
    with pytest.raises(HTTPException) as exc:
        get_product_for_admin(db, 10**9)
    assert exc.value.status_code == 404


def test_base_fields_can_be_edited(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Old", "slug": "edit-1", "brand": "Pixi", "category_id": cat.id,
    })

    updated = update_product(db, actor, p.id, {"title": "New", "brand": "Pixi"})

    assert updated.title == "New"


def test_base_slug_must_stay_ascii(db):
    """products.slug has an ASCII allowlist; only translation slugs take Arabic."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-2", "brand": "Pixi", "category_id": cat.id,
    })

    with pytest.raises(HTTPException) as exc:
        update_product(db, actor, p.id, {"slug": "صندل"})

    assert exc.value.status_code == 400


def test_archiving_leaves_the_row_in_place(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-3", "brand": "Pixi", "category_id": cat.id,
    })

    archive_product(db, actor, p.id)

    db.refresh(p)
    assert p.status == "archived"
    assert db.get(Product, p.id) is not None


def test_archiving_unpublishes_every_language(db):
    """An archived product must stop being served, in both locales."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-4", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })
    publish_product(db, actor, p.id, "ar")

    archive_product(db, actor, p.id)

    tr = db.execute(
        select(ProductTranslation).where(ProductTranslation.product_id == p.id)
    ).scalar_one()
    assert tr.is_published is False


def _variant(db, actor, slug: str):
    cat = _level2_category(db)
    p = create_product(db, actor, {
        "title": "V", "slug": slug, "brand": "Pixi", "category_id": cat.id,
    })
    return generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})[0]


def test_catalog_role_can_change_price_and_stock(db):
    actor = _actor(db)
    v = _variant(db, actor, "var-1")

    updated = update_variant(db, actor, v.id, {"price": "450.00", "stock_quantity": 9})

    assert updated.price == Decimal("450.00")
    assert updated.stock_quantity == 9


def test_catalog_role_cannot_set_cogs(db):
    actor = _actor(db)             # role="catalog"
    v = _variant(db, actor, "var-2")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"cost": "200.00"})

    assert exc.value.status_code == 403


def test_admin_role_can_set_cogs(db):
    admin = User(
        email="cogs-admin@example.com", password_hash="x",
        full_name="Admin", role="admin", is_active=True,
    )
    db.add(admin)
    db.flush()
    v = _variant(db, admin, "var-3")

    updated = update_variant(db, admin, v.id, {"cost": "200.00"})

    assert updated.cost == Decimal("200.00")


def test_sale_price_above_price_is_rejected_on_update(db):
    actor = _actor(db)
    v = _variant(db, actor, "var-4")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"sale_price": "900.00"})

    assert exc.value.status_code == 400


def test_sku_cannot_be_changed(db):
    """trg_variants_sku_immutable enforces it; the API refuses before it fires."""
    actor = _actor(db)
    v = _variant(db, actor, "var-5")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"sku": "REWRITTEN-1"})

    assert exc.value.status_code == 400
    assert "immutable" in exc.value.detail.lower()


def test_deactivating_the_default_variant_reassigns_another_active_one(db):
    """Controller ruling (cross-task correction): is_active becoming editable
    makes a previously-latent bug live. publish_readiness only checked
    default_variant_id IS NOT NULL, never whether that variant was still
    active -- until now nothing could deactivate a variant, so an active
    product could never end up pointing at a disabled default. Reassigning to
    another active variant (mirroring publish_product's own self-heal of a
    cleared default_variant_id) keeps a deactivation from silently leaving the
    product's default disabled while readiness still says "ready"."""
    actor = _actor(db)
    cat = _level2_category(db)
    p = create_product(db, actor, {
        "title": "V", "slug": "var-default-1", "brand": "Pixi", "category_id": cat.id,
    })
    variants = generate_variants(
        db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"}
    )
    db.refresh(p)
    default_id = p.default_variant_id
    assert default_id == variants[0].id

    update_variant(db, actor, default_id, {"is_active": False})

    db.refresh(p)
    assert p.default_variant_id != default_id
    assert p.default_variant_id == variants[1].id


def test_deactivating_the_only_active_variant_that_is_default_is_rejected(db):
    """No active variant remains to reassign to, and nulling default_variant_id
    on an active(-eligible) product would violate
    ck_products_active_has_default_variant -- refuse instead."""
    actor = _actor(db)
    v = _variant(db, actor, "var-default-2")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"is_active": False})

    assert exc.value.status_code == 409


def test_readiness_reports_no_default_variant_when_it_is_inactive(db):
    """Tightens publish_readiness itself (not just update_variant's guard): the
    referenced default variant must still be active, not merely non-NULL, or
    a product whose default was deactivated by some other path keeps reporting
    "ready" to publish."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-8", "brand": "Pixi", "category_id": cat.id,
    })
    variants = generate_variants(
        db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"}
    )
    db.refresh(p)
    assert p.default_variant_id == variants[0].id
    variants[0].is_active = False
    db.flush()

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "no_default_variant" in codes


# --- Review fixes (I1, I2, I3, minors) --------------------------------------


def test_updating_to_a_colliding_slug_raises_409_not_500_on_the_race(db, monkeypatch):
    """I1: update_product had a pre-check but no catch around the flush --
    create_product already fixed exactly this race (commit 0b380e5, F1): pre-
    check, then a concurrent rename landing between the check and the flush
    surfaces as an unhandled IntegrityError -> 500 instead of 409. Simulated
    here without real concurrency by making the pre-check's own query report
    "nothing taken" on its first call, even though the colliding slug already
    exists -- exactly what a same-slug rename racing in on another connection
    would look like from inside this flush."""
    cat, actor = _level2_category(db), _actor(db)
    create_product(db, actor, {
        "title": "Taken", "slug": "race-taken", "brand": "Pixi", "category_id": cat.id,
    })
    p = create_product(db, actor, {
        "title": "Mover", "slug": "race-mover", "brand": "Pixi", "category_id": cat.id,
    })

    real_execute = db.execute
    calls = {"n": 0}

    def _fake_execute(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            class _EmptyResult:
                def first(self_inner):
                    return None
            return _EmptyResult()
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(db, "execute", _fake_execute)

    with pytest.raises(HTTPException) as exc:
        update_product(db, actor, p.id, {"slug": "race-taken"})

    assert exc.value.status_code == 409


def test_resending_the_same_sku_is_a_noop(db):
    actor = _actor(db)
    v = _variant(db, actor, "var-6")

    updated = update_variant(db, actor, v.id, {"sku": v.sku, "price": "460.00"})

    assert updated.sku == v.sku
    assert updated.price == Decimal("460.00")


def test_sku_null_is_not_treated_as_a_change(db):
    """I2: admin_variant_update now carries an sku field, so an explicit
    ``"sku": null`` reaches the repository instead of being dropped by
    Pydantic. NULL must not be read as "change the SKU to nothing" -- the
    column is NOT NULL and immutable -- just as "no SKU change requested"."""
    actor = _actor(db)
    v = _variant(db, actor, "var-7")

    updated = update_variant(db, actor, v.id, {"sku": None, "price": "470.00"})

    assert updated.sku == v.sku
    assert updated.price == Decimal("470.00")


def test_negative_price_is_rejected(db):
    """Minor: ck_variants_price_non_negative would otherwise surface a
    negative price as a raw 500 at flush."""
    actor = _actor(db)
    v = _variant(db, actor, "var-8")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"price": "-1.00"})

    assert exc.value.status_code == 400


def test_negative_cost_is_rejected_for_an_admin(db):
    """Minor: ck_variants_cost_non_negative, same reasoning as price."""
    admin = User(
        email="cogs-admin-2@example.com", password_hash="x",
        full_name="Admin", role="admin", is_active=True,
    )
    db.add(admin)
    db.flush()
    v = _variant(db, admin, "var-9")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, admin, v.id, {"cost": "-1.00"})

    assert exc.value.status_code == 400


def test_shipping_dimensions_are_editable(db):
    """Minor: length_cm/width_cm/height_cm are in _EDITABLE_VARIANT_FIELDS but
    were absent from admin_variant_update -- dead capability at the schema
    layer. The repository has always accepted them (given properly-typed
    values, as Pydantic would produce); this pins that down directly."""
    actor = _actor(db)
    v = _variant(db, actor, "var-10")

    updated = update_variant(db, actor, v.id, {
        "length_cm": Decimal("12.50"), "width_cm": Decimal("8.00"),
        "height_cm": Decimal("5.25"),
    })

    assert updated.length_cm == Decimal("12.50")
    assert updated.width_cm == Decimal("8.00")
    assert updated.height_cm == Decimal("5.25")
