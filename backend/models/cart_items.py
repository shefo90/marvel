"""Cart lines.

``UNIQUE (cart_id, variant_id)`` is what makes section 15's "cart add/remove
quantities and values are correct after rapid repeated clicks" pass: concurrent
adds of the same variant collide on the constraint and become a single
``INSERT ... ON CONFLICT DO UPDATE``, instead of two rows racing.

The price snapshot is taken at add time and re-checked at checkout, so a price
change between adding and paying is detected rather than silently applied.

``added_from_list_id`` / ``added_from_list_name`` carry section 5's
``item_list_id`` / ``item_list_name`` from the surface the shopper selected
from, and are copied to ``order_items`` at conversion — the "revenue by
collection" decision. This context is impossible to reconstruct later.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import DiscountSource
from models.mixins import TimestampMixin


class CartItem(Base, TimestampMixin):
    __tablename__ = "cart_items"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cart_id = mapped_column(
        BigInteger, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    variant_id = mapped_column(BigInteger, nullable=False)
    # Denormalized so the composite FK below can prove the SKU matches the
    # variant. Section 2's identifier contract, enforced by the database.
    sku = mapped_column(String(64), nullable=False)

    quantity = mapped_column(Integer, nullable=False, server_default="1")
    unit_price_snapshot = mapped_column(Numeric(12, 2), nullable=False)
    unit_sale_price_snapshot = mapped_column(Numeric(12, 2), nullable=True)
    price_snapshot_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_repriced_at = mapped_column(DateTime(timezone=True), nullable=True)

    added_from_list_id = mapped_column(String(64), nullable=True)
    added_from_list_name = mapped_column(String(160), nullable=True)
    added_from_index = mapped_column(Integer, nullable=True)
    item_coupon_code = mapped_column(String(64), nullable=True)

    # Section 4.4 attribution. Which offer priced this line, how much it took
    # off, and which mechanism it was -- a markdown is not a campaign cost, and
    # only the promotion rows feed orders.promotion_cost_total.
    promotion_id = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True
    )
    discount_amount = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    discount_source = mapped_column(
        SAEnum(DiscountSource, native_enum=False, length=16), nullable=True
    )

    cart = relationship("Cart", back_populates="items")
    variant = relationship(
        "ProductVariant", back_populates="cart_items", foreign_keys=[variant_id]
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["variant_id", "sku"],
            ["product_variants.id", "product_variants.sku"],
            name="fk_cart_items_variant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("cart_id", "variant_id", name="uq_cart_items_cart_variant"),
        CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
        CheckConstraint(
            "unit_price_snapshot >= 0 "
            "AND (unit_sale_price_snapshot IS NULL OR unit_sale_price_snapshot >= 0)",
            name="ck_cart_items_prices_non_negative",
        ),
        Index("ix_cart_items_cart_id", "cart_id"),
        Index("ix_cart_items_variant_id", "variant_id"),
    )
