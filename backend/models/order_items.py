"""One row per sellable unit purchased.

Two snapshots live here, and both matter:

* **Catalog snapshot** (sku, title, variant attributes, brand, category path,
  price) so the line stays readable and reconcilable even if the product row is
  later edited, renamed or archived.
* **COGS snapshot** — section 11A: "Persist product COGS at order-item level as
  a historical snapshot... Do not recalculate old orders from today's product
  cost." ``unit_cogs`` is copied from the variant at order creation and is never
  re-read from the catalog afterwards.

``item_list_id`` / ``item_list_name`` are carried from the cart line so revenue
can be attributed to the merchandising surface the shopper actually bought from
("Summer Edit") and not only to the category. That browsing context cannot be
reconstructed after the fact, which is why it is captured here rather than
derived later.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    line_number = mapped_column(Integer, nullable=False)

    # --- Identity (section 2). variant_id + sku are FK-checked together. ---
    product_id = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=True
    )
    variant_id = mapped_column(BigInteger, nullable=False)
    sku = mapped_column(String(64), nullable=False)
    item_group_id = mapped_column(String(64), nullable=True)

    # --- Catalog snapshot -------------------------------------------------
    product_title = mapped_column(String(255), nullable=False)
    variant_label = mapped_column(String(160), nullable=True)
    variant_attributes = mapped_column(JSONB, nullable=False, server_default="{}")
    brand = mapped_column(String(120), nullable=True)
    category_path = mapped_column(String(255), nullable=True)
    product_url = mapped_column(Text, nullable=True)

    # --- Section 5 list attribution --------------------------------------
    item_list_id = mapped_column(String(64), nullable=True)
    item_list_name = mapped_column(String(160), nullable=True)

    # --- Money ------------------------------------------------------------
    unit_list_price = mapped_column(Numeric(12, 2), nullable=True)
    unit_price = mapped_column(Numeric(12, 2), nullable=False)
    quantity = mapped_column(Integer, nullable=False)
    discount_amount = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    coupon_code = mapped_column(String(64), nullable=True)
    line_subtotal = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    line_total = mapped_column(Numeric(12, 2), nullable=False)

    # --- Section 11A historical cost snapshot -----------------------------
    unit_cogs = mapped_column(Numeric(12, 2), nullable=True)
    line_cogs = mapped_column(Numeric(12, 2), nullable=True)
    # 'variant_cost' when the catalog had a cost, 'unknown' when it did not —
    # so a null margin is distinguishable from a genuinely zero one.
    cogs_snapshot_source = mapped_column(String(32), nullable=True)

    # --- Refund/return state (section 15 partial refunds) -----------------
    refunded_quantity = mapped_column(Integer, nullable=False, server_default="0")
    refunded_amount = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    restocked_quantity = mapped_column(Integer, nullable=False, server_default="0")

    order = relationship("Order", back_populates="items")
    variant = relationship(
        "ProductVariant", back_populates="order_items", foreign_keys=[variant_id]
    )
    refund_items = relationship("RefundItem", back_populates="order_item")

    __table_args__ = (
        # A persisted SKU that disagrees with its variant is rejected outright.
        ForeignKeyConstraint(
            ["variant_id", "sku"],
            ["product_variants.id", "product_variants.sku"],
            name="fk_order_items_variant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("order_id", "line_number", name="uq_order_items_line_number"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0 AND discount_amount >= 0 AND line_subtotal >= 0 "
            "AND line_total >= 0 AND tax_amount >= 0",
            name="ck_order_items_amounts_non_negative",
        ),
        CheckConstraint(
            "unit_cogs IS NULL OR unit_cogs >= 0", name="ck_order_items_cogs_non_negative"
        ),
        CheckConstraint(
            "refunded_quantity >= 0 AND refunded_quantity <= quantity",
            name="ck_order_items_refunded_quantity",
        ),
        CheckConstraint(
            "restocked_quantity >= 0 AND restocked_quantity <= quantity",
            name="ck_order_items_restocked_quantity",
        ),
        CheckConstraint(
            "refunded_amount >= 0 AND refunded_amount <= line_total",
            name="ck_order_items_refunded_amount",
        ),
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_variant_id", "variant_id"),
        Index("ix_order_items_sku", "sku"),
        Index("ix_order_items_list", "item_list_id"),
    )
