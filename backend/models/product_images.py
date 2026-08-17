"""Product and variant imagery.

``width``/``height`` are NOT NULL because section 8A requires explicit image
dimensions to hold CLS under 0.1 — a missing dimension is a layout-shift bug
waiting to happen, so the database refuses it.

``alt_text`` here is the base (English) value; per-locale alt text lives in
``product_image_translations``.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class ProductImage(Base, TimestampMixin):
    __tablename__ = "product_images"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    variant_id = mapped_column(BigInteger, nullable=True)
    url = mapped_column(String(500), nullable=False)
    alt_text = mapped_column(String(255), nullable=False)
    width = mapped_column(Integer, nullable=False)
    height = mapped_column(Integer, nullable=False)
    is_primary = mapped_column(Boolean, nullable=False, server_default="false")
    position = mapped_column(Integer, nullable=False, server_default="0")

    product = relationship("Product", back_populates="images")
    variant = relationship(
        "ProductVariant", back_populates="images", foreign_keys=[variant_id]
    )
    translations = relationship(
        "ProductImageTranslation",
        back_populates="image",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # An image can never be attached to a variant of a different product.
        # MATCH SIMPLE makes the constraint inert when variant_id is NULL.
        ForeignKeyConstraint(
            ["product_id", "variant_id"],
            ["product_variants.product_id", "product_variants.id"],
            name="fk_product_images_variant",
            ondelete="CASCADE",
        ),
        CheckConstraint("width > 0 AND height > 0", name="ck_product_images_dimensions"),
        CheckConstraint(
            "length(btrim(alt_text)) > 0", name="ck_product_images_alt_text_not_blank"
        ),
        UniqueConstraint(
            "product_id",
            "variant_id",
            "position",
            name="uq_product_images_position",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_product_images_primary_product",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary AND variant_id IS NULL"),
        ),
        Index(
            "uq_product_images_primary_variant",
            "variant_id",
            unique=True,
            postgresql_where=text("is_primary AND variant_id IS NOT NULL"),
        ),
        Index("ix_product_images_product_id", "product_id", "position"),
    )
