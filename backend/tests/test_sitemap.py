"""Sitemaps and robots.txt — section 8A.

Membership is not invented here. ``ix_product_translations_sitemap`` already
defines it as a partial index:

    is_published AND robots_index AND is_complete AND canonical_override IS NULL

so the query matches that predicate exactly, and the index serves it. A sitemap
that lists a page Google should not index is worse than no sitemap: it is a
direct request to crawl something we told it to ignore.
"""

from datetime import datetime, timezone
from xml.etree import ElementTree

import pytest
from sqlalchemy import select

from models.categories import Category
from models.locales import Locale
from models.product_translations import ProductTranslation
from models.products import Product
from repositories.sitemap import robots_txt, sitemap_entries, sitemap_index

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
      "xhtml": "http://www.w3.org/1999/xhtml"}


def _locale(db, code: str) -> None:
    if db.get(Locale, code) is None:
        db.add(Locale(
            code=code, hreflang=code, name_native=code,
            text_direction="rtl" if code == "ar" else "ltr",
            is_default=(code == "en"), is_active=True, sort_order=1,
        ))
        db.flush()


def _category(db) -> Category:
    existing = db.query(Category).filter(Category.slug == "sitemap-child").first()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="S1", slug="sitemap-top", list_id="sitemap_top",
        position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="S2", slug="sitemap-child",
        list_id="sitemap_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _product(db, slug: str, status: str = "active") -> Product:
    """An active product needs a default variant.

    ck_products_active_has_default_variant says so, which is why this builds
    one: a product nobody can buy has no business being in a sitemap either.
    """
    from decimal import Decimal

    from models.product_variants import ProductVariant

    product = Product(
        item_group_id=f"SITEMAP-{slug.upper()}", slug=slug, title=slug, brand="Pixi",
        category_id=_category(db).id, status="draft", tags=[], condition="new",
    )
    db.add(product)
    db.flush()

    variant = ProductVariant(
        product_id=product.id, sku=f"SITEMAP-{slug.upper()}-38",
        variant_title="38 / black", size="38", color="black", attributes={},
        price=Decimal("500.00"), currency="EGP", availability="in_stock",
        stock_quantity=5, merchant_eligible=True, is_active=True,
    )
    db.add(variant)
    db.flush()

    product.default_variant_id = variant.id
    product.status = status
    db.flush()
    return product


def _translation(db, product, locale: str, slug: str, **overrides) -> ProductTranslation:
    _locale(db, locale)
    values = {
        "title": "A sandal", "description": "A description",
        "meta_description": "A meta description", "is_published": True,
        "robots_index": True, "translation_source": "human",
    }
    values.update(overrides)
    translation = ProductTranslation(
        product_id=product.id, locale=locale, slug=slug, **values
    )
    db.add(translation)
    db.flush()
    return translation


def _slugs(entries) -> set[str]:
    return {entry["loc"].rsplit("/", 1)[-1] for entry in entries}


def test_a_published_product_is_listed(db):
    product = _product(db, "sitemap-live")
    _translation(db, product, "en", "sitemap-live-en")

    assert "sitemap-live-en" in _slugs(sitemap_entries(db, "en"))


def test_a_draft_translation_is_not_listed(db):
    product = _product(db, "sitemap-draft")
    _translation(db, product, "en", "sitemap-draft-en", is_published=False)

    assert "sitemap-draft-en" not in _slugs(sitemap_entries(db, "en"))


def test_a_noindex_translation_is_not_listed(db):
    """Listing a page we told Google not to index is a direct contradiction."""
    product = _product(db, "sitemap-noindex")
    _translation(db, product, "en", "sitemap-noindex-en", robots_index=False)

    assert "sitemap-noindex-en" not in _slugs(sitemap_entries(db, "en"))


def test_a_translation_with_a_canonical_override_is_not_listed(db):
    """It declares another URL as the real one, so this is a duplicate."""
    product = _product(db, "sitemap-canonical")
    _translation(
        db, product, "en", "sitemap-canonical-en",
        canonical_override="https://marvel.com/en/products/elsewhere",
    )

    assert "sitemap-canonical-en" not in _slugs(sitemap_entries(db, "en"))


def test_an_incomplete_translation_is_not_listed(db):
    """is_complete is generated from description and meta_description. A row
    missing either cannot be published at all, but it can be un-published and
    still carry robots_index -- the predicate needs all four parts."""
    product = _product(db, "sitemap-incomplete")
    _translation(
        db, product, "en", "sitemap-incomplete-en",
        description=None, meta_description=None, is_published=False,
    )

    assert "sitemap-incomplete-en" not in _slugs(sitemap_entries(db, "en"))


def test_a_product_that_is_not_active_is_not_listed(db):
    """A published translation on an archived product is still a 404 to a
    shopper, and archiving unpublishes anyway -- this is belt and braces on the
    one join the index cannot express."""
    product = _product(db, "sitemap-archived", status="archived")
    _translation(db, product, "en", "sitemap-archived-en")

    assert "sitemap-archived-en" not in _slugs(sitemap_entries(db, "en"))


def test_each_entry_carries_its_last_modified_date(db):
    """Without lastmod a crawler has no reason to revisit a changed page."""
    product = _product(db, "sitemap-lastmod")
    _translation(db, product, "en", "sitemap-lastmod-en")

    entry = next(
        e for e in sitemap_entries(db, "en") if e["loc"].endswith("sitemap-lastmod-en")
    )

    assert isinstance(entry["lastmod"], datetime)


def test_a_product_in_both_languages_declares_both_as_alternates(db):
    """Section 8A: the hreflang cluster must be reciprocal, and each member
    lists every member including itself."""
    product = _product(db, "sitemap-both")
    _translation(db, product, "en", "sitemap-both-en")
    _translation(db, product, "ar", "sitemap-both-ar")

    entry = next(
        e for e in sitemap_entries(db, "en") if e["loc"].endswith("sitemap-both-en")
    )

    assert set(entry["alternates"]) == {"en", "ar"}
    assert entry["alternates"]["ar"].endswith("/ar/products/sitemap-both-ar")


def test_a_product_in_one_language_declares_no_alternates(db):
    """A cluster of one emits no hreflang at all -- a self-referential cluster
    is noise, not a signal."""
    product = _product(db, "sitemap-single")
    _translation(db, product, "en", "sitemap-single-en")

    entry = next(
        e for e in sitemap_entries(db, "en") if e["loc"].endswith("sitemap-single-en")
    )

    assert entry["alternates"] == {}


def test_a_draft_sibling_is_not_an_alternate(db):
    """An unpublished Arabic page is a 404. Pointing hreflang at it tells Google
    the cluster is broken."""
    product = _product(db, "sitemap-half")
    _translation(db, product, "en", "sitemap-half-en")
    _translation(db, product, "ar", "sitemap-half-ar", is_published=False)

    entry = next(
        e for e in sitemap_entries(db, "en") if e["loc"].endswith("sitemap-half-en")
    )

    assert entry["alternates"] == {}


def test_locations_are_absolute_urls(db):
    """A sitemap with relative URLs is rejected outright."""
    product = _product(db, "sitemap-absolute")
    _translation(db, product, "en", "sitemap-absolute-en")

    entry = next(
        e for e in sitemap_entries(db, "en") if e["loc"].endswith("sitemap-absolute-en")
    )

    assert entry["loc"].startswith("http")


def test_the_index_lists_one_sitemap_per_active_locale(db):
    _locale(db, "en")
    _locale(db, "ar")

    xml = sitemap_index(db)

    root = ElementTree.fromstring(xml)
    locations = [node.text for node in root.findall("sm:sitemap/sm:loc", NS)]
    assert any(loc.endswith("/sitemap-en.xml") for loc in locations)
    assert any(loc.endswith("/sitemap-ar.xml") for loc in locations)


def test_robots_points_at_the_sitemap_index(db):
    text = robots_txt()

    assert "Sitemap: " in text
    assert "/sitemap.xml" in text


def test_robots_keeps_crawlers_out_of_the_admin(db):
    """Section 2.1: /admin is excluded from robots and from the sitemap."""
    text = robots_txt()

    assert "Disallow: /admin" in text


def test_robots_keeps_crawlers_out_of_cart_and_checkout(db):
    """Per-shopper pages have nothing to index and burn crawl budget."""
    text = robots_txt()

    assert "Disallow: /cart" in text
    assert "Disallow: /checkout" in text


# --- Over HTTP --------------------------------------------------------------


def test_robots_is_served_as_plain_text(client):
    r = client.get("/robots.txt")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "Disallow: /admin" in r.text


def test_the_sitemap_index_is_served_as_xml(client):
    r = client.get("/sitemap.xml")

    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    ElementTree.fromstring(r.text)


def test_a_locale_sitemap_is_well_formed(client):
    r = client.get("/sitemap-en.xml")

    assert r.status_code == 200
    root = ElementTree.fromstring(r.text)
    assert root.tag.endswith("urlset")


def test_an_unknown_locale_sitemap_is_a_404_not_an_empty_one(client):
    """Section 8A forbids soft 404s: an empty urlset at HTTP 200 tells a
    crawler the language exists and simply has no pages."""
    r = client.get("/sitemap-fr.xml")

    assert r.status_code == 404
