"""The feed timestamps that drive S6's incremental catalog sync.

``catalog_updated_at``, ``inventory_updated_at`` and ``content_updated_at``
exist so a feed run can ask "what changed since last time?" instead of pushing
the whole catalogue. Nothing wrote them, so the honest answer was always
"nothing" and every edited variant was silently skipped.

These tests pin the *field filter*, which is the part that is easy to get wrong.
A stock correction is not a catalog change: pushing it to Merchant Center as one
costs a re-review for no reason. A COGS edit is neither -- cost appears in no
feed at all, and bumping a feed timestamp for it would push a payload whose
every visible field is identical.

The rows are created with an old timestamp and the edit is asserted to move it,
rather than comparing against wall-clock time: ``now()`` is the *transaction*
timestamp in Postgres and does not advance within one transaction, so a
create-then-edit in a single test would otherwise compare a value to itself.
"""

from datetime import datetime, timezone
from decimal import Decimal

from models.categories import Category
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product

OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _category(db) -> Category:
    from sqlalchemy import select

    existing = db.execute(
        select(Category).where(Category.slug == "feedts-child")
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="F1", slug="feedts-top",
        list_id="feedts_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="F2", slug="feedts-child",
        list_id="feedts_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _variant(db, slug: str) -> ProductVariant:
    """A variant whose three feed timestamps are all parked in 2020."""
    product = Product(
        item_group_id=f"FEEDTS-{slug.upper()}", slug=slug, title=slug,
        brand="Pixi", category_id=_category(db).id, status="draft", tags=[],
        condition="new",
    )
    db.add(product)
    db.flush()
    variant = ProductVariant(
        product_id=product.id, sku=f"FEEDTS-{slug.upper()}-38",
        variant_title="38 / black", size="38", color="black", attributes={},
        price=Decimal("100.00"), currency="EGP", availability="in_stock",
        stock_quantity=10, merchant_eligible=True, is_active=True,
    )
    db.add(variant)
    db.flush()

    variant.catalog_updated_at = OLD
    variant.inventory_updated_at = OLD
    db.flush()
    # An explicit timestamp write is not itself a catalog change, or parking the
    # clock would be impossible.
    assert variant.catalog_updated_at == OLD
    assert variant.inventory_updated_at == OLD
    return variant


def test_a_price_edit_moves_catalog_updated_at(db):
    variant = _variant(db, "feedts-price")

    variant.price = Decimal("125.00")
    db.flush()

    assert variant.catalog_updated_at > OLD


def test_a_price_edit_leaves_inventory_updated_at_alone(db):
    """Merchant re-reviews an offer whose catalog fields move. Stock is not one."""
    variant = _variant(db, "feedts-price-inv")

    variant.price = Decimal("125.00")
    db.flush()

    assert variant.inventory_updated_at == OLD


def test_a_stock_edit_moves_inventory_updated_at(db):
    variant = _variant(db, "feedts-stock")

    variant.stock_quantity = 3
    db.flush()

    assert variant.inventory_updated_at > OLD


def test_a_stock_edit_leaves_catalog_updated_at_alone(db):
    variant = _variant(db, "feedts-stock-cat")

    variant.stock_quantity = 3
    db.flush()

    assert variant.catalog_updated_at == OLD


def test_a_cost_edit_moves_neither_timestamp(db):
    """COGS is internal. It appears in no feed, so it triggers no feed work."""
    variant = _variant(db, "feedts-cost")

    variant.cost = Decimal("42.00")
    db.flush()

    assert variant.catalog_updated_at == OLD
    assert variant.inventory_updated_at == OLD


def test_an_availability_edit_moves_inventory_updated_at(db):
    variant = _variant(db, "feedts-avail")

    variant.availability = "out_of_stock"
    db.flush()

    assert variant.inventory_updated_at > OLD
    assert variant.catalog_updated_at == OLD


def test_a_translation_edit_moves_content_updated_at(db):
    """content_updated_at is what the sitemap reports as lastmod."""
    variant = _variant(db, "feedts-content")
    translation = ProductTranslation(
        product_id=variant.product_id, locale="en", slug="feedts-content-en",
        title="Before", description="d", meta_description="m",
    )
    db.add(translation)
    db.flush()
    translation.content_updated_at = OLD
    db.flush()

    translation.title = "After"
    db.flush()

    assert translation.content_updated_at > OLD
