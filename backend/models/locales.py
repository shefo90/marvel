"""Supported locales.

A reference table rather than a PostgreSQL native ENUM (design section 6.1), so
adding a locale is a row insert instead of an ``ALTER TYPE``.
"""

from sqlalchemy import Boolean, CheckConstraint, Index, SmallInteger, String, Text, text
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class Locale(Base):
    __tablename__ = "locales"

    code = mapped_column(String(5), primary_key=True)
    hreflang = mapped_column(String(10), nullable=False)
    name_native = mapped_column(Text, nullable=False)
    text_direction = mapped_column(String(3), nullable=False)
    is_default = mapped_column(Boolean, nullable=False, server_default="false")
    is_active = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order = mapped_column(SmallInteger, nullable=False, server_default="0")

    product_translations = relationship(
        "ProductTranslation", back_populates="locale_ref"
    )
    category_translations = relationship(
        "CategoryTranslation", back_populates="locale_ref"
    )
    collection_translations = relationship(
        "CollectionTranslation", back_populates="locale_ref"
    )

    __table_args__ = (
        CheckConstraint(r"code ~ '^[a-z]{2}$'", name="ck_locales_code_format"),
        CheckConstraint(
            "text_direction IN ('ltr','rtl')", name="ck_locales_text_direction"
        ),
        # Exactly one default locale. x-default points at it (design section 6.3).
        Index(
            "uq_locales_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )
