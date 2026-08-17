"""Per-locale image alt text.

Section 8A requires descriptive alt text on indexable images; the Arabic page
needs Arabic alt text or it is silently shipping English to Arabic readers and
to image search.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class ProductImageTranslation(Base, TimestampMixin):
    __tablename__ = "product_image_translations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_image_id = mapped_column(
        BigInteger, ForeignKey("product_images.id", ondelete="CASCADE"), nullable=False
    )
    locale = mapped_column(
        String(5), ForeignKey("locales.code", onupdate="CASCADE"), nullable=False
    )
    alt_text = mapped_column(Text, nullable=False)
    title_attr = mapped_column(Text, nullable=True)

    image = relationship("ProductImage", back_populates="translations")

    __table_args__ = (
        UniqueConstraint(
            "product_image_id", "locale", name="uq_product_image_translations_image_locale"
        ),
        CheckConstraint(
            "btrim(alt_text) <> ''", name="ck_product_image_translations_alt_not_blank"
        ),
    )
