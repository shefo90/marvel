"""Category pages, collections, filters, facets and sorting.

Two pieces of cache discipline hold this file together, both because these
fixtures live on the rolled-back session and must never outlive it in Redis.

Every test scopes its listing to a category of its own, with a uuid slug:
``list_products`` caches, and the key includes the category slug, so two tests
querying an unscoped listing would share a key and the second would be served
the first one's rolled-back products.

The tree has no such natural key -- it caches under ``(locale, "tree")`` -- so
``fresh_taxonomy`` drops the namespace on the way *in*, to build from this
session, and again on the way *out*, so uncommitted categories are not left in
the cache for the next test or for a developer's running app.
"""

import uuid
from decimal import Decimal

import pytest

from models.categories import Category
from models.category_translations import CategoryTranslation
from repositories.admin_catalog import (
    create_product,
    generate_variants,
    publish_product,
    update_variant,
    upsert_translation,
)
from repositories.product import list_products
from repositories.taxonomy import (
    category_tree,
    get_category,
    get_collection,
    invalidate_taxonomy,
)
from tests.test_admin_writes import _actor, _locale


@pytest.fixture(autouse=True)
def fresh_taxonomy():
    """See the module docstring: in and out, every test."""
    invalidate_taxonomy()
    yield
    invalidate_taxonomy()


def _category(db, *, parent=None, title="Sandals") -> Category:
    """A category with an English translation, which is what the storefront
    resolves a slug through."""
    tag = uuid.uuid4().hex[:10]
    category = Category(
        parent_id=parent.id if parent else None,
        level=2 if parent else 1,
        name=title,
        slug=f"{title.lower()}-{tag}",
        list_id=f"cat_{tag}",
        position=1,
        is_active=True,
        is_indexable=True,
    )
    db.add(category)
    db.flush()
    db.add(CategoryTranslation(
        category_id=category.id, locale="en", title=title, slug=f"{title.lower()}-{tag}",
        description=f"{title} for every step", meta_description=f"Shop {title}",
        is_published=True,
    ))
    db.flush()
    return category


def _product(db, category, *, title, sizes, colors, price="1000.00", stock=5):
    actor = _actor(db)
    slug = f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"
    product = create_product(db, actor, {
        "title": title, "slug": slug, "brand": "Pixi", "category_id": category.id,
    })
    variants = generate_variants(db, actor, product.id, sizes, colors, {
        "price": price, "stock_quantity": stock,
    })
    upsert_translation(db, actor, product.id, "en", {
        "title": title, "slug": slug, "description": f"{title} description",
        "meta_description": f"Buy {title}",
    })
    publish_product(db, actor, product.id, "en")
    return product, variants


@pytest.fixture
def shop(db):
    """Two products in one category: a cheap black/beige sandal in 38-39, and a
    dearer black-only heel in 40."""
    _locale(db, "en")
    parent = _category(db, title="Shoes")
    category = _category(db, parent=parent, title="Sandals")
    sandal, sandal_variants = _product(
        db, category, title="Strap Sandal", sizes=["38", "39"],
        colors=["black", "beige"], price="900.00",
    )
    heel, heel_variants = _product(
        db, category, title="Evening Heel", sizes=["40"], colors=["black"],
        price="1800.00",
    )
    return {
        "category": category,
        "parent": parent, "sandal": sandal, "heel": heel,
        "sandal_variants": sandal_variants, "heel_variants": heel_variants,
    }


def _slug(db, category) -> str:
    return db.execute(
        CategoryTranslation.__table__.select().where(
            CategoryTranslation.category_id == category.id
        )
    ).one().slug


def _titles(result) -> list[str]:
    return [item["title"] for item in result["items"]]


# --- the navigation tree -------------------------------------------------

def test_the_tree_nests_level_two_under_its_parent(db, shop):
    tree = category_tree(db, "en")

    parents = {node["slug"]: node for node in tree}
    parent_slug = _slug(db, shop["parent"])
    assert parent_slug in parents
    assert _slug(db, shop["category"]) in {
        child["slug"] for child in parents[parent_slug]["children"]
    }


def test_a_level_two_category_is_never_a_root(db, shop):
    """A child rendered at the top of the menu would sit beside Shoes and Bags
    as though it were their peer."""
    roots = {node["slug"] for node in category_tree(db, "en")}

    assert _slug(db, shop["category"]) not in roots


def test_a_category_carries_its_parent_for_the_breadcrumb(db, shop):
    detail = get_category(db, "en", _slug(db, shop["category"]))

    assert detail["parent"]["slug"] == _slug(db, shop["parent"])


def test_an_unknown_category_slug_is_none_not_an_empty_page(db):
    assert get_category(db, "en", f"missing-{uuid.uuid4().hex[:8]}") is None
    assert get_collection(db, "en", f"missing-{uuid.uuid4().hex[:8]}") is None


# --- filtering -----------------------------------------------------------

def test_a_category_listing_shows_only_that_categorys_products(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["category"]))

    assert sorted(_titles(result)) == ["Evening Heel", "Strap Sandal"]


def test_a_level_one_category_shows_everything_under_it(db, shop):
    """The "View all" bug.

    products.category_level is generated as 2 with a composite FK, so a product
    can only ever hang off a level-2 category. Matching the named row alone made
    every top-level page -- the ones the navigation and every "View all" link
    point at -- permanently empty, while its children worked fine.
    """
    result = list_products(db, "en", category_slug=_slug(db, shop["parent"]))

    assert sorted(_titles(result)) == ["Evening Heel", "Strap Sandal"]


def test_a_level_one_category_offers_facets_from_all_its_children(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["parent"]))

    assert {f["code"] for f in result["facets"]["sizes"]} == {"38", "39", "40"}


def test_an_unknown_category_slug_matches_nothing_not_everything(db, shop):
    """A typo in a category URL must not quietly render the whole catalogue."""
    result = list_products(db, "en", category_slug=f"typo-{uuid.uuid4().hex[:8]}")

    assert result["items"] == []
    assert result["total"] == 0


def test_filtering_by_size_narrows_the_listing(db, shop):
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sizes=["40"]
    )

    assert _titles(result) == ["Evening Heel"]


def test_size_and_colour_must_be_satisfied_by_one_variant(db, shop):
    """Asking for a beige 40 must return nothing: the beige sandal has no 40 and
    the 40 heel is not beige. Matching the filters independently would show the
    shopper a product they cannot buy in the combination they asked for."""
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]),
        sizes=["40"], colors=["beige"],
    )

    assert result["items"] == []


def test_an_out_of_stock_variant_can_be_filtered_out(db, shop):
    actor = _actor(db)
    for variant in shop["heel_variants"]:
        update_variant(db, actor, variant.id, {"stock_quantity": 0})

    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), in_stock=True
    )

    assert _titles(result) == ["Strap Sandal"]


# --- facets --------------------------------------------------------------

def test_facets_offer_every_size_in_the_category(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["category"]))

    assert {f["code"] for f in result["facets"]["sizes"]} == {"38", "39", "40"}


def test_a_facet_does_not_narrow_itself(db, shop):
    """The subtle one. Size counts are computed with the size filter ignored, so
    picking 40 leaves 38 and 39 still offered -- they are exactly the boxes that
    would widen the result. Counting them under their own filter would show 0
    beside each and tell the shopper the opposite of the truth."""
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sizes=["40"]
    )

    offered = {f["code"]: f["count"] for f in result["facets"]["sizes"]}
    assert offered.get("38"), "picking 40 hid every other size"
    assert offered.get("39")


def test_a_facet_records_which_values_are_selected(db, shop):
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sizes=["40"]
    )

    selected = {f["code"] for f in result["facets"]["sizes"] if f["selected"]}
    assert selected == {"40"}


def test_a_facet_is_narrowed_by_the_other_facet(db, shop):
    """Colour must still constrain the size counts, or the two filters would be
    independent and the counts would promise combinations that do not exist."""
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), colors=["beige"]
    )

    assert {f["code"] for f in result["facets"]["sizes"]} == {"38", "39"}


def test_the_price_bounds_span_the_scope(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["category"]))

    assert Decimal(result["facets"]["price"]["min"]) == Decimal("900.00")
    assert Decimal(result["facets"]["price"]["max"]) == Decimal("1800.00")


# --- sorting -------------------------------------------------------------

def test_sorting_by_price_uses_the_price_on_the_card(db, shop):
    """A markdown is the price the shopper sees, so it is the price they expect
    to be sorted by. Sorting on list price puts the cheapest-looking product
    halfway down the page."""
    actor = _actor(db)
    for variant in shop["heel_variants"]:
        update_variant(db, actor, variant.id, {"sale_price": "100.00"})

    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sort="price_asc"
    )

    assert _titles(result) == ["Evening Heel", "Strap Sandal"]


def test_sorting_by_price_descending_reverses_it(db, shop):
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sort="price_desc"
    )

    assert _titles(result) == ["Evening Heel", "Strap Sandal"]


def test_an_unknown_sort_falls_back_to_featured(db, shop):
    result = list_products(
        db, "en", category_slug=_slug(db, shop["category"]), sort="by-vibes"
    )

    assert result["sort"] == "featured"


# --- the card ------------------------------------------------------------

def test_a_card_carries_its_colours_and_in_stock_sizes(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["category"]))

    sandal = next(i for i in result["items"] if i["title"] == "Strap Sandal")
    assert {c["code"] for c in sandal["colors"]} == {"black", "beige"}
    assert {s["code"] for s in sandal["sizes"]} == {"38", "39"}


def test_a_card_without_a_second_image_offers_no_hover_swap(db, shop):
    result = list_products(db, "en", category_slug=_slug(db, shop["category"]))

    assert all(item["hover_image"] is None for item in result["items"])
