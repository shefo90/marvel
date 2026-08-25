"""One pricing implementation, exercised directly.

The worst defect in this project's history was two customer-identity normalizers
that disagreed: one shopper resolved into two ``customers`` rows and every
lifetime-value figure was wrong while each individual test passed. Pricing has
the identical shape — if the cart prices one way and checkout another, the
shopper sees one number and is charged a different one, which is exactly the
"price mismatch" Merchant Center diagnostics flag.

So there is one function, and ``test_cart_and_orders.py`` asserts the two paths
agree on the same basket.

**The money shape matters and is easy to get backwards.** A markdown is not a
campaign cost:

* ``unit_list_price`` is the catalogue price
* ``unit_price`` is what the catalogue currently asks — the sale price if there
  is one — so a markdown shows up as ``unit_list_price - unit_price``
* ``discount_amount`` is what a *promotion* took off on top of that, and only
  that feeds ``orders.promotion_cost_total``
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from models.categories import Category
from models.collection_products import CollectionProduct
from models.collections import Collection
from models.products import Product
from models.promotion_targets import PromotionTarget
from models.promotions import Promotion
from repositories.pricing import price_basket


def _category(db) -> Category:
    existing = db.query(Category).filter(Category.slug == "pricing-child").first()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="P1", slug="pricing-top",
        list_id="pricing_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="P2", slug="pricing-child",
        list_id="pricing_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _variant(db, slug: str, price: str, sale_price: str | None = None):
    from models.product_variants import ProductVariant

    category = _category(db)
    product = Product(
        item_group_id=f"PRICE-{slug.upper()}", slug=slug, title=slug,
        brand="Pixi", category_id=category.id, status="draft", tags=[],
        condition="new",
    )
    db.add(product)
    db.flush()
    variant = ProductVariant(
        product_id=product.id, sku=f"PRICE-{slug.upper()}-38",
        variant_title="38 / black", size="38", color="black", attributes={},
        price=Decimal(price),
        sale_price=Decimal(sale_price) if sale_price is not None else None,
        currency="EGP", availability="in_stock", stock_quantity=10,
        merchant_eligible=True, is_active=True,
    )
    db.add(variant)
    db.flush()
    return variant


def _promotion(db, **kwargs) -> Promotion:
    targets = kwargs.pop("targets", [])
    promotion = Promotion(
        name=kwargs.pop("name", "Test offer"),
        is_active=kwargs.pop("is_active", True),
        **kwargs,
    )
    db.add(promotion)
    db.flush()
    for target_type, target_id in targets:
        db.add(PromotionTarget(
            promotion_id=promotion.id, target_type=target_type, target_id=target_id
        ))
    db.flush()
    return promotion


def _percentage(db, percent: str, targets, **kwargs) -> Promotion:
    return _promotion(
        db, type="percentage", discount_percent=Decimal(percent), targets=targets, **kwargs
    )


# --- no offers --------------------------------------------------------------


def test_a_plain_variant_is_priced_at_its_price(db):
    variant = _variant(db, "plain", "500.00")

    line = price_basket(db, [(variant, 2)])[0]

    assert line.unit_list_price == Decimal("500.00")
    assert line.unit_price == Decimal("500.00")
    assert line.discount_amount == Decimal("0.00")
    assert line.line_total == Decimal("1000.00")
    assert line.promotion_id is None
    assert line.discount_source is None


def test_a_sale_price_is_a_markdown_not_a_campaign_cost(db):
    """It shows as unit_list_price - unit_price and stays out of
    discount_amount, so promotion_cost_total does not absorb it."""
    variant = _variant(db, "marked-down", "500.00", "400.00")

    line = price_basket(db, [(variant, 1)])[0]

    assert line.unit_list_price == Decimal("500.00")
    assert line.unit_price == Decimal("400.00")
    assert line.discount_amount == Decimal("0.00")
    assert line.discount_source == "sale_price"
    assert line.promotion_id is None


# --- targeting --------------------------------------------------------------


def test_a_promotion_with_no_targets_applies_to_nothing(db):
    """Explicitly, so a half-saved offer cannot mark the whole catalogue down."""
    variant = _variant(db, "untargeted", "500.00")
    _percentage(db, "50", targets=[])

    line = price_basket(db, [(variant, 1)])[0]

    assert line.discount_amount == Decimal("0.00")


def test_target_all_applies_to_everything(db):
    variant = _variant(db, "target-all", "500.00")
    _percentage(db, "10", targets=[("all", None)])

    line = price_basket(db, [(variant, 1)])[0]

    assert line.discount_amount == Decimal("50.00")
    assert line.discount_source == "promotion"


def test_a_product_target_applies_to_its_variants(db):
    variant = _variant(db, "target-product", "500.00")
    _percentage(db, "10", targets=[("product", variant.product_id)])

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("50.00")


def test_a_variant_target_applies_to_that_variant_alone(db):
    included = _variant(db, "target-variant-in", "500.00")
    excluded = _variant(db, "target-variant-out", "500.00")
    _percentage(db, "10", targets=[("variant", included.id)])

    lines = price_basket(db, [(included, 1), (excluded, 1)])

    assert lines[0].discount_amount == Decimal("50.00")
    assert lines[1].discount_amount == Decimal("0.00")


def test_a_category_target_applies_to_products_in_it(db):
    variant = _variant(db, "target-category", "500.00")
    _percentage(db, "20", targets=[("category", _category(db).id)])

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("100.00")


def test_a_collection_target_applies_to_its_members(db):
    variant = _variant(db, "target-collection", "500.00")
    collection = Collection(
        list_id="pricing_coll", name="Eid", slug="eid-pricing", position=1,
        is_active=True, is_indexable=True,
    )
    db.add(collection)
    db.flush()
    db.add(CollectionProduct(collection_id=collection.id, product_id=variant.product_id))
    db.flush()
    _percentage(db, "10", targets=[("collection", collection.id)])

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("50.00")


# --- the window and the switch ----------------------------------------------


def test_an_inactive_promotion_is_not_a_candidate(db):
    variant = _variant(db, "inactive-promo", "500.00")
    _percentage(db, "50", targets=[("all", None)], is_active=False)

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("0.00")


def test_a_promotion_that_has_not_started_is_not_a_candidate(db):
    variant = _variant(db, "future-promo", "500.00")
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    _percentage(db, "50", targets=[("all", None)], starts_at=tomorrow)

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("0.00")


def test_an_expired_promotion_is_not_a_candidate(db):
    variant = _variant(db, "expired-promo", "500.00")
    now = datetime.now(timezone.utc)
    _percentage(
        db, "50", targets=[("all", None)],
        starts_at=now - timedelta(days=2), ends_at=now - timedelta(days=1),
    )

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("0.00")


def test_an_open_ended_window_is_live(db):
    variant = _variant(db, "open-window", "500.00")
    _percentage(db, "10", targets=[("all", None)], starts_at=None, ends_at=None)

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("50.00")


# --- best single discount wins ----------------------------------------------


def test_the_deepest_discount_wins(db):
    variant = _variant(db, "best-wins", "500.00")
    _percentage(db, "10", targets=[("all", None)], name="Weak")
    deep = _percentage(db, "30", targets=[("all", None)], name="Deep")

    line = price_basket(db, [(variant, 1)])[0]

    assert line.discount_amount == Decimal("150.00")
    assert line.promotion_id == deep.id


def test_a_line_never_carries_two_promotions(db):
    """No stacking. Two 20% offers are 20% off, not 40% and not 36%."""
    variant = _variant(db, "no-stacking", "500.00")
    _percentage(db, "20", targets=[("all", None)], name="First")
    _percentage(db, "20", targets=[("all", None)], name="Second")

    line = price_basket(db, [(variant, 1)])[0]

    assert line.discount_amount == Decimal("100.00")


def test_a_fixed_amount_promotion_comes_off_the_list_price(db):
    variant = _variant(db, "fixed-off", "500.00")
    _promotion(
        db, type="fixed", discount_amount=Decimal("75.00"), targets=[("all", None)]
    )

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("75.00")


def test_a_promotion_can_never_price_a_line_below_zero(db):
    """A fixed 600 off a 500 shoe is 500 off, not a refund."""
    variant = _variant(db, "over-discount", "500.00")
    _promotion(
        db, type="fixed", discount_amount=Decimal("600.00"), targets=[("all", None)]
    )

    line = price_basket(db, [(variant, 1)])[0]

    assert line.line_total == Decimal("0.00")
    assert line.discount_amount == Decimal("500.00")


def test_a_sale_price_deeper_than_the_promotion_keeps_the_markdown(db):
    """400 on sale beats 10% off 500. The line is a markdown, and no campaign
    cost is recorded for an offer that changed nothing."""
    variant = _variant(db, "sale-beats-promo", "500.00", "400.00")
    _percentage(db, "10", targets=[("all", None)])

    line = price_basket(db, [(variant, 1)])[0]

    assert line.unit_price == Decimal("400.00")
    assert line.discount_amount == Decimal("0.00")
    assert line.discount_source == "sale_price"
    assert line.promotion_id is None


def test_a_promotion_deeper_than_the_sale_price_charges_only_the_difference(db):
    """The campaign cost is what the promotion added, not the whole gap from
    list. Section 4.4: markdowns stay visible without being counted as spend."""
    variant = _variant(db, "promo-beats-sale", "500.00", "450.00")
    _percentage(db, "20", targets=[("all", None)])  # 400 off list

    line = price_basket(db, [(variant, 1)])[0]

    assert line.unit_price == Decimal("450.00")
    assert line.discount_amount == Decimal("50.00")
    assert line.line_total == Decimal("400.00")
    assert line.discount_source == "promotion"


# --- BOGO -------------------------------------------------------------------


def _bogo(db, buy, get, percent, targets, **kwargs):
    return _promotion(
        db, type="bogo", buy_quantity=buy, get_quantity=get,
        get_discount_percent=Decimal(percent), targets=targets, **kwargs
    )


def test_buy_one_get_one_free_discounts_one_unit_of_two(db):
    variant = _variant(db, "bogo-simple", "500.00")
    _bogo(db, 1, 1, "100", targets=[("all", None)])

    line = price_basket(db, [(variant, 2)])[0]

    assert line.discount_amount == Decimal("500.00")
    assert line.line_total == Decimal("500.00")
    assert line.discount_source == "promotion"


def test_bogo_does_nothing_below_the_threshold(db):
    variant = _variant(db, "bogo-below", "500.00")
    _bogo(db, 1, 1, "100", targets=[("all", None)])

    assert price_basket(db, [(variant, 1)])[0].discount_amount == Decimal("0.00")


def test_bogo_applies_once_per_complete_chunk(db):
    """Five units under buy-1-get-1 is two complete pairs and one loose unit:
    two discounted, not two and a half."""
    variant = _variant(db, "bogo-chunks", "100.00")
    _bogo(db, 1, 1, "100", targets=[("all", None)])

    line = price_basket(db, [(variant, 5)])[0]

    assert line.discount_amount == Decimal("200.00")


def test_a_partial_bogo_discounts_only_that_share(db):
    """Buy 2 get 1 half price: three units, half off the third."""
    variant = _variant(db, "bogo-partial", "300.00")
    _bogo(db, 2, 1, "50", targets=[("all", None)])

    line = price_basket(db, [(variant, 3)])[0]

    assert line.discount_amount == Decimal("150.00")


def test_bogo_discounts_the_cheapest_units_in_each_chunk(db):
    """Across lines, not within one. Units are ranked by price descending and
    the free one is the cheapest in its group -- the shopper does not get the
    expensive shoe free by adding a cheap one."""
    expensive = _variant(db, "bogo-expensive", "900.00")
    cheap = _variant(db, "bogo-cheap", "100.00")
    _bogo(db, 1, 1, "100", targets=[("all", None)])

    lines = {line.variant_id: line for line in price_basket(db, [(expensive, 1), (cheap, 1)])}

    assert lines[expensive.id].discount_amount == Decimal("0.00")
    assert lines[cheap.id].discount_amount == Decimal("100.00")


def test_bogo_only_counts_units_it_targets(db):
    included = _variant(db, "bogo-target-in", "500.00")
    excluded = _variant(db, "bogo-target-out", "500.00")
    _bogo(db, 1, 1, "100", targets=[("variant", included.id)])

    lines = {line.variant_id: line for line in price_basket(db, [(included, 1), (excluded, 1)])}

    # One targeted unit is not a complete pair, whatever else is in the basket.
    assert lines[included.id].discount_amount == Decimal("0.00")
    assert lines[excluded.id].discount_amount == Decimal("0.00")


def test_the_better_of_bogo_and_a_percentage_wins(db):
    """Buy-1-get-1 on two units is 50% of the line; a 10% offer is not close.
    Whichever gives the shopper more is the one that applies -- never both."""
    variant = _variant(db, "bogo-vs-percent", "500.00")
    _percentage(db, "10", targets=[("all", None)], name="Ten percent")
    bogo = _bogo(db, 1, 1, "100", targets=[("all", None)])

    line = price_basket(db, [(variant, 2)])[0]

    assert line.discount_amount == Decimal("500.00")
    assert line.promotion_id == bogo.id


def test_a_percentage_beats_a_thin_bogo(db):
    """Buy 4 get 1 at 10% off is worth far less than 30% off everything."""
    variant = _variant(db, "percent-vs-bogo", "500.00")
    percentage = _percentage(db, "30", targets=[("all", None)])
    _bogo(db, 4, 1, "10", targets=[("all", None)])

    line = price_basket(db, [(variant, 5)])[0]

    assert line.promotion_id == percentage.id
    assert line.discount_amount == Decimal("750.00")


def test_bogo_is_computed_against_the_sale_price_not_the_list_price(db):
    """A free unit of a marked-down shoe costs the marked-down price, not the
    list price -- otherwise the discount exceeds what was ever charged."""
    variant = _variant(db, "bogo-on-sale", "500.00", "400.00")
    _bogo(db, 1, 1, "100", targets=[("all", None)])

    line = price_basket(db, [(variant, 2)])[0]

    assert line.discount_amount == Decimal("400.00")
    assert line.line_total == Decimal("400.00")


def test_every_amount_is_quantized_to_two_places(db):
    """Money is Numeric(12,2). A third decimal place would be rounded by the
    database rather than by us, which is where cart and order totals drift
    apart."""
    variant = _variant(db, "rounding", "333.33")
    _percentage(db, "33.33", targets=[("all", None)])

    line = price_basket(db, [(variant, 3)])[0]

    assert line.discount_amount == line.discount_amount.quantize(Decimal("0.01"))
    assert line.line_total == line.line_total.quantize(Decimal("0.01"))


def test_an_empty_basket_prices_to_nothing(db):
    assert price_basket(db, []) == []
