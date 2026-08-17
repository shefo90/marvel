"""Per-locale collection content."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TranslationMixin, translation_table_args


class CollectionTranslation(Base, TranslationMixin):
    __tablename__ = "collection_translations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id = mapped_column(
        BigInteger, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )

    collection = relationship("Collection", back_populates="translations")
    locale_ref = relationship("Locale", back_populates="collection_translations")

    __table_args__ = translation_table_args("collection_translations", "collection_id")
