"""Per-locale product content.

Only rows with ``is_published`` AND ``is_complete`` are hreflang cluster members
and sitemap candidates (design section 6.2). A product with only an English
translation emits no hreflang at all.
"""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TranslationMixin, translation_table_args


class ProductTranslation(Base, TranslationMixin):
    __tablename__ = "product_translations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )

    product = relationship("Product", back_populates="translations")
    locale_ref = relationship("Locale", back_populates="product_translations")

    __table_args__ = translation_table_args("product_translations", "product_id")
