"""Per-locale labels for variant attribute values.

This is what turns "black" into "أسود" on the Arabic size/colour selector.
Without it the Arabic product page renders English attribute labels.
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


class AttributeValueTranslation(Base, TimestampMixin):
    __tablename__ = "attribute_value_translations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attribute_value_id = mapped_column(
        BigInteger, ForeignKey("attribute_values.id", ondelete="CASCADE"), nullable=False
    )
    locale = mapped_column(
        String(5), ForeignKey("locales.code", onupdate="CASCADE"), nullable=False
    )
    label = mapped_column(Text, nullable=False)

    attribute_value = relationship("AttributeValue", back_populates="translations")

    __table_args__ = (
        UniqueConstraint(
            "attribute_value_id",
            "locale",
            name="uq_attribute_value_translations_value_locale",
        ),
        CheckConstraint(
            "btrim(label) <> ''", name="ck_attribute_value_translations_label_not_blank"
        ),
    )
