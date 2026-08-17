"""Canonical variant-attribute values (size / color / material).

Added to close a gap in the design: ``attribute_value_translations`` referenced
an owner table that no domain modeled, so the Arabic label for "Black" had
nowhere to live.

Relationship to ``product_variants`` is a **soft reference**: a variant stores
the canonical ``code`` string in its ``size`` / ``color`` / ``material`` column
rather than a foreign key. That keeps variant creation from being blocked on
attribute seeding, at the cost of needing a reconciliation check — see
``scripts/check_attribute_values.py`` — to catch a variant using a value that
has no row here and therefore no Arabic label.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import AttributeType
from models.mixins import TimestampMixin


class AttributeValue(Base, TimestampMixin):
    __tablename__ = "attribute_values"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attribute_type = mapped_column(
        SAEnum(AttributeType, native_enum=False, length=16), nullable=False
    )
    # The canonical value as stored on product_variants (e.g. "black", "38").
    code = mapped_column(String(64), nullable=False)
    # Base (English) display label. Arabic lives in the translation table.
    label = mapped_column(String(120), nullable=False)
    sort_order = mapped_column(SmallInteger, nullable=False, server_default="0")
    is_active = mapped_column(Boolean, nullable=False, server_default="true")

    translations = relationship(
        "AttributeValueTranslation",
        back_populates="attribute_value",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("attribute_type", "code", name="uq_attribute_values_type_code"),
        CheckConstraint(
            "length(btrim(code)) > 0", name="ck_attribute_values_code_not_blank"
        ),
        Index("ix_attribute_values_type", "attribute_type", "sort_order"),
    )
