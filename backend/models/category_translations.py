"""Per-locale category content."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TranslationMixin, translation_table_args


class CategoryTranslation(Base, TranslationMixin):
    __tablename__ = "category_translations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )

    category = relationship("Category", back_populates="translations")
    locale_ref = relationship("Locale", back_populates="category_translations")

    __table_args__ = translation_table_args("category_translations", "category_id")
