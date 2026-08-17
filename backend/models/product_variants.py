"""THE sellable unit.

One row = one SKU = one Merchant ``offer_id`` = one GA4/Ads ``item_id`` = one
Meta/TikTok/Snap ``content_id`` = one ``order_items`` line target.

This table is where section 2's identifier contract is enforced. ``sku`` is
immutable — a BEFORE UPDATE trigger (added in the migration) raises on change,
which makes section 2's "never regenerate" unfalsifiable rather than merely
documented.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import Availability
from models.mixins import TimestampMixin


class ProductVariant(Base, TimestampMixin):
    __tablename__ = "product_variants"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )

    # --- Section 2 identifier contract -----------------------------------
    sku = mapped_column(String(64), nullable=False)
    gtin = mapped_column(String(14), nullable=True)
    mpn = mapped_column(String(64), nullable=True)

    # --- Variant attributes ----------------------------------------------
    variant_title = mapped_column(String(160), nullable=False)
    size = mapped_column(String(32), nullable=True)
    # Merchant rejects footwear offers with ambiguous sizing (open question 11).
    size_system = mapped_column(String(8), nullable=True)
    color = mapped_column(String(64), nullable=True)
    material = mapped_column(String(64), nullable=True)
    attributes = mapped_column(JSONB, nullable=False, server_default="{}")

    # --- Money. Single market, single currency: EGP only. -----------------
    price = mapped_column(Numeric(12, 2), nullable=False)
    sale_price = mapped_column(Numeric(12, 2), nullable=True)
    currency = mapped_column(String(3), nullable=False, server_default="EGP")
    # Current cost. Order lines snapshot this at purchase time and never read it
    # again (section 11A: do not recalculate old orders from today's cost).
    cost = mapped_column(Numeric(12, 2), nullable=True)

    # --- Inventory --------------------------------------------------------
    availability = mapped_column(
        SAEnum(Availability, native_enum=False, length=16),
        nullable=False,
        server_default=Availability.in_stock.value,
    )
    stock_quantity = mapped_column(Integer, nullable=False, server_default="0")
    inventory_updated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- Shipping attributes (section 8, section 10) ----------------------
    weight_grams = mapped_column(Integer, nullable=True)
    length_cm = mapped_column(Numeric(6, 2), nullable=True)
    width_cm = mapped_column(Numeric(6, 2), nullable=True)
    height_cm = mapped_column(Numeric(6, 2), nullable=True)

    merchant_eligible = mapped_column(Boolean, nullable=False, server_default="true")
    is_active = mapped_column(Boolean, nullable=False, server_default="true")
    catalog_updated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product = relationship(
        "Product", back_populates="variants", foreign_keys=[product_id]
    )
    # Read-only: an image is attached to a *product* and optionally tagged with
    # a variant, so writes go through Product.images or ProductImage.variant.
    # Making this viewonly resolves the overlap between the composite FK
    # (product_id, variant_id) and the plain product_id FK.
    images = relationship(
        "ProductImage",
        back_populates="variant",
        order_by="ProductImage.position",
        viewonly=True,
    )
    cart_items = relationship("CartItem", back_populates="variant")
    order_items = relationship("OrderItem", back_populates="variant")

    __table_args__ = (
        UniqueConstraint("sku", name="uq_product_variants_sku"),
        # Composite FK targets. order_items(variant_id, sku) and
        # cart_items(variant_id, sku) reference (id, sku), so a persisted SKU
        # string that disagrees with its variant is rejected by the database.
        UniqueConstraint("id", "sku", name="uq_product_variants_id_sku"),
        UniqueConstraint("product_id", "id", name="uq_product_variants_product_id"),
        UniqueConstraint(
            "product_id",
            "size",
            "color",
            "material",
            name="uq_product_variants_combination",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("price >= 0", name="ck_variants_price_non_negative"),
        CheckConstraint(
            "sale_price IS NULL OR (sale_price >= 0 AND sale_price <= price)",
            name="ck_variants_sale_price_valid",
        ),
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_variants_cost_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="ck_variants_stock_non_negative"),
        CheckConstraint("currency = 'EGP'", name="ck_variants_currency_egp"),
        CheckConstraint(
            "size_system IS NULL OR size IS NOT NULL", name="ck_variants_size_system"
        ),
        CheckConstraint(r"sku ~ '^[A-Z0-9][A-Z0-9-]*$'", name="ck_variants_sku_format"),
        Index("ix_product_variants_product_id", "product_id"),
        Index(
            "uq_product_variants_gtin",
            "gtin",
            unique=True,
            postgresql_where=text("gtin IS NOT NULL"),
        ),
        Index(
            "ix_product_variants_availability",
            "availability",
            postgresql_where=text("is_active"),
        ),
        # Section 8 incremental catalog sync.
        Index(
            "ix_product_variants_feed_pending",
            "catalog_updated_at",
            postgresql_where=text("merchant_eligible AND is_active"),
        ),
        # Section 13 stale-inventory alerting.
        Index("ix_product_variants_inventory_updated_at", "inventory_updated_at"),
    )
