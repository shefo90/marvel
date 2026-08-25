"""Catalog locale rules, and the customer-identity invariant.

The identity test is a regression guard for a defect that shipped and was caught
only by cross-checking two layers: registration and checkout each had their own
phone normalizer, and they disagreed (``201001234567`` vs ``+201001234567``).
The same shopper resolved to two ``customer_identity`` rows and two customers,
silently corrupting section 11A's lifetime-value layer. Nothing failed loudly.
"""

import pytest

from repositories import order as order_repo
from repositories import register as register_repo
from services import identity

# --- Customer identity ---------------------------------------------------

EG_PHONE_FORMS = [
    "01001234567",
    "0100 123 4567",
    "+20 100 123 4567",
    "+201001234567",
    "0020 100 123 4567",
    "00201001234567",
    "201001234567",
]


@pytest.mark.parametrize("raw", EG_PHONE_FORMS)
def test_all_egyptian_phone_forms_collapse_to_one_identity(raw):
    assert identity.normalize_phone(raw) == "+201001234567"


@pytest.mark.parametrize("raw", EG_PHONE_FORMS)
def test_registration_and_checkout_normalize_phones_identically(raw):
    """If these ever diverge, one shopper becomes two customers."""
    assert register_repo.normalize_phone(raw) == order_repo._normalize_phone(raw)


@pytest.mark.parametrize(
    "raw", ["Shopper@Example.com", "  spaced@example.com  ", "UPPER@EXAMPLE.COM"]
)
def test_registration_and_checkout_normalize_emails_identically(raw):
    assert register_repo.normalize_email(raw) == order_repo._normalize_email(raw)


def test_email_normalization_does_not_strip_provider_specific_forms():
    """Stripping Gmail dots or +tags would merge genuinely distinct people."""
    assert identity.normalize_email("a.b+tag@gmail.com") == "a.b+tag@gmail.com"


def test_identity_hash_is_64_hex_chars():
    """customer_identity CHECKs the length."""
    digest = identity.sha256_hex("+201001234567")
    assert len(digest) == 64
    assert digest == digest.lower()


# --- Catalog locale behaviour --------------------------------------------


def test_unknown_locale_404s(client):
    """Section 8A forbids rendering content at 200 under an unrecognised locale."""
    assert client.get("/api/fr/products").status_code == 404


def test_arabic_listing_excludes_untranslated_products(client):
    en = client.get("/api/en/products").json()
    ar = client.get("/api/ar/products").json()
    assert en["total"] > ar["total"]


def test_untranslated_product_404s_rather_than_falling_back(client):
    """Falling back to English would create a near-duplicate Arabic page and
    make the hreflang cluster claim a translation that does not exist."""
    assert client.get("/api/en/products/woven-flat-sandal").status_code == 200
    assert client.get("/api/ar/products/woven-flat-sandal").status_code == 404


def test_single_locale_product_emits_no_hreflang(client):
    body = client.get("/api/en/products/woven-flat-sandal").json()
    assert body["alternates"] == {}


def test_bilingual_product_emits_reciprocal_alternates(client):
    body = client.get("/api/en/products/leather-strap-sandal").json()
    assert set(body["alternates"]) == {"en", "ar"}


def test_arabic_slug_resolves(client):
    r = client.get("/api/ar/products/صندل-جلد-بحزام")
    assert r.status_code == 200
    assert r.json()["locale"] == "ar"


def test_listing_carries_item_list_identity(client):
    """Section 5: the same list id must reach the dataLayer, cart and order."""
    body = client.get("/api/en/products", params={"collection": "summer-edit"}).json()
    assert body["item_list_id"] == "summer_edit"
    assert body["items"][0]["index"] == 0


def test_price_bearing_response_is_not_long_cached(client):
    """A stale cached price IS the 'price mismatch' defect section 8 monitors."""
    r = client.get("/api/en/products/leather-strap-sandal")
    assert "max-age=60" in r.headers.get("cache-control", "")


def test_a_listing_row_carries_the_sku_whose_price_it_advertises(client):
    """Section 2 makes the SKU the sellable identifier and says it is the same
    value GA4 and Ads use. Without it on a listing row, view_item_list and
    select_item have no item_id at all -- every join from a list impression to
    revenue breaks, silently, because GA4 accepts the event regardless.

    The SKU is the cheapest active variant's: that is the variant whose price
    the row is showing, so attributing the impression to any other would
    advertise one price and identify a different item.
    """
    body = client.get("/api/en/products").json()
    assert body["items"], "seed data must provide at least one listed product"

    row = body["items"][0]
    detail = client.get(f"/api/en/products/{row['slug']}").json()

    assert row["sku"], "listing rows must carry an item_id for analytics"
    assert row["sku"] in {variant["sku"] for variant in detail["variants"]}
