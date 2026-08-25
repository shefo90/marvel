"""Search, and the Arabic folding that decides whether it works.

Open question 1, closed. The folding rules are alef/hamza/taa-marbuta/alef
maqsura, with diacritics and tatweel stripped, applied before tokenization.

**The variant table below is the whole point of this file.** Postgres's built-in
``arabic`` configuration already handles diacritics, tatweel and alef madda, so
it is tempting to conclude no folding is needed. Measured on this database it is
inconsistent in exactly the places a shopper types:

    'مقهى'    -> 'مقه'    but  'مقهي'    -> 'مقهي'
    'الأحذية' -> 'احذ'    but  'الاحذيه' -> 'احذيه'

The second pair is not exotic. ``الاحذيه`` is how the word arrives from a phone
keyboard when nobody is reaching for hamza, and without folding that shopper
searches the shop's largest category and is told it is empty.

Each pair below is asserted to find the *same* product, which is a statement
about the shopper's experience rather than about tokens.
"""

import uuid
from decimal import Decimal

import pytest

from models.categories import Category
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from repositories.search import search_products

# (what is written on the product, what the shopper types) — every pair must
# find it. The English rows are here because folding must not break the case
# that already worked.
VARIANTS = [
    ("مقهى", "مقهي"),            # alef maqsura vs yaa
    ("الأحذية", "الاحذيه"),      # hamza + taa marbuta vs the plain spelling
    ("حِذَاء", "حذاء"),           # harakat vs none
    ("حــذاء", "حذاء"),          # tatweel vs none
    ("أحذية", "احذيه"),          # both endings differ
    ("صَنْدَل", "صندل"),          # harakat again, a word the shop actually sells
    ("Sandal", "sandal"),        # English, case only
]


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _category(db) -> Category:
    from sqlalchemy import select

    existing = db.execute(
        select(Category).where(Category.slug == "search-child")
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="S1", slug="search-top",
        list_id="search_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="S2", slug="search-child",
        list_id="search_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


# Long enough to be realistic. The first version of this fixture defaulted the
# description to the title, which made every stored document one or two words --
# and that is what let a broken typo clause pass. similarity() against a
# two-word document scores high; against a real seventy-character description it
# scores 0.08 and matches nothing. A fixture shorter than production data does
# not test production behaviour.
FILLER = (
    "A soft leather upper with an adjustable ankle strap and a cushioned "
    "footbed, made for long summer days in the city."
)


def _published(db, *, title, locale="ar", description="", brand="Pixi") -> Product:
    """A product a shopper could actually reach: active, with a live variant and
    a published translation. Search must not surface anything else."""
    slug = f"search-{_tag()}"
    product = Product(
        item_group_id=f"SRCH-{slug.upper()}", slug=slug, title=title,
        brand=brand, category_id=_category(db).id, status="draft", tags=[],
        condition="new",
    )
    db.add(product)
    db.flush()

    variant = ProductVariant(
        product_id=product.id, sku=f"SRCH-{slug.upper()}-38",
        variant_title="38 / black", size="38", color="black", attributes={},
        price=Decimal("400.00"), currency="EGP", availability="in_stock",
        stock_quantity=5, merchant_eligible=True, is_active=True,
    )
    db.add(variant)
    db.flush()

    product.default_variant_id = variant.id
    product.status = "active"
    db.add(ProductTranslation(
        product_id=product.id, locale=locale, slug=f"{slug}-{locale}",
        title=title, description=description or f"{title} — {FILLER}",
        meta_description=title, is_published=True,
    ))
    db.flush()
    return product


@pytest.fixture
def locales(db):
    from tests.test_admin_writes import _locale

    _locale(db, "en")
    _locale(db, "ar")


@pytest.mark.parametrize("written,typed", VARIANTS)
def test_a_shopper_finds_the_product_however_they_spell_it(db, locales, written, typed):
    locale = "en" if written.isascii() else "ar"
    product = _published(db, title=written, locale=locale)

    found = search_products(db, locale, typed)

    found_ids = [row["id"] for row in found["items"]]
    assert product.id in found_ids, f"{typed!r} did not find a product titled {written!r}"


def test_search_finds_a_word_inside_the_description(db, locales):
    product = _published(
        db, title="حذاء", description="صندل من الجلد الطبيعي", locale="ar"
    )

    found = search_products(db, "ar", "الجلد")

    assert product.id in [row["id"] for row in found["items"]]


def test_search_matches_a_brand(db, locales):
    product = _published(db, title="Sandal", locale="en", brand="Larkspur")

    found = search_products(db, "en", "larkspur")

    assert product.id in [row["id"] for row in found["items"]]


def test_an_english_plural_finds_a_singular_title(db, locales):
    """The reason the tsvector is locale-aware. Under the arabic config English
    is not stemmed at all, so this would miss."""
    product = _published(db, title="Suede Sandal", locale="en")

    found = search_products(db, "en", "sandals")

    assert product.id in [row["id"] for row in found["items"]]


def test_a_prefix_finds_the_product(db, locales):
    """What the trigram index is for. A tsvector cannot answer this."""
    product = _published(db, title="Espadrille", locale="en")

    found = search_products(db, "en", "espad")

    assert product.id in [row["id"] for row in found["items"]]


def test_a_typo_still_finds_the_product(db, locales):
    product = _published(db, title="Espadrille", locale="en")

    found = search_products(db, "en", "espadrile")

    assert product.id in [row["id"] for row in found["items"]]


def test_an_empty_query_returns_nothing_rather_than_everything(db, locales):
    """A blank search that returns the catalogue looks like a broken filter, and
    on a big catalogue it is an accidental full scan."""
    _published(db, title="Sandal", locale="en")

    assert search_products(db, "en", "")["items"] == []
    assert search_products(db, "en", "   ")["items"] == []


def test_a_query_matching_nothing_returns_an_empty_page(db, locales):
    found = search_products(db, "en", "xylophone-and-a-half")

    assert found["items"] == []
    assert found["total"] == 0


def test_a_draft_product_is_not_searchable(db, locales):
    """Search is a storefront read. It must obey the same visibility rules as
    every other one: a draft is not a thing a shopper may find."""
    product = _published(db, title="Secret Sandal", locale="en")
    product.status = "draft"
    db.flush()

    found = search_products(db, "en", "secret")

    assert product.id not in [row["id"] for row in found["items"]]


def test_search_does_not_leak_the_other_locale(db, locales):
    """An Arabic product with no English translation is absent from an English
    search: the storefront resolves a product through its translation, so a
    result with none is a link to a page that cannot render."""
    product = _published(db, title="صندل جلد", locale="ar")

    found = search_products(db, "en", "صندل")

    assert product.id not in [row["id"] for row in found["items"]]


def test_the_query_is_reported_back(db, locales):
    """The results page prints it, and the GA4 search event sends it. Echoing
    the normalized-but-not-mangled original keeps both honest."""
    found = search_products(db, "en", "  Sandal  ")

    assert found["query"] == "Sandal"


# --- over HTTP -----------------------------------------------------------

def test_the_search_endpoint_echoes_the_query(client):
    r = client.get("/api/en/search", params={"q": "sandal"})

    assert r.status_code == 200, r.text
    assert r.json()["query"] == "sandal"


def test_the_search_endpoint_reports_its_own_list_identity(client):
    """Section 5: search impressions have to be separable from browse
    impressions, so they carry their own item_list_id rather than a category's."""
    r = client.get("/api/en/search", params={"q": "sandal"})

    assert r.json()["item_list_id"] == "search"


def test_an_over_long_query_is_refused_rather_than_run(client):
    """A search box is a text input pointed at the database. 120 characters is
    past anything a person means."""
    r = client.get("/api/en/search", params={"q": "x" * 500})

    assert r.status_code == 422


def test_a_search_response_is_not_shared_cacheable(client):
    """A search URL is per-shopper. A shared cache holding one stores somebody's
    query against a key another person can reach."""
    r = client.get("/api/en/search", params={"q": "sandal"})

    assert "private" in r.headers.get("cache-control", "")


def test_search_works_in_arabic_over_http(client):
    r = client.get("/api/ar/search", params={"q": "صندل"})

    assert r.status_code == 200, r.text
    assert r.json()["query"] == "صندل"
