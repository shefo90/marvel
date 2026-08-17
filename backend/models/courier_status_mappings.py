"""Provider status string -> normalized internal status.

Section 10: "Do not assume Bosta endpoint names/status strings in business code;
confirm against the account's current API documentation during implementation."

Keeping the mapping in data rather than code means a provider renaming a status
is a row update, not a deploy — and an *unmapped* status is detectable rather
than silently swallowed.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ShipmentStatus
from models.mixins import TimestampMixin


class CourierStatusMapping(Base, TimestampMixin):
    __tablename__ = "courier_status_mappings"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_id = mapped_column(
        BigInteger, ForeignKey("courier_providers.id", ondelete="CASCADE"), nullable=False
    )
    provider_status = mapped_column(String(128), nullable=False)
    provider_reason_code = mapped_column(String(64), nullable=True)
    internal_status = mapped_column(
        SAEnum(ShipmentStatus, native_enum=False, length=32), nullable=False
    )
    is_terminal = mapped_column(Boolean, nullable=False, server_default="false")
    notes = mapped_column(Text, nullable=True)

    provider = relationship("CourierProvider", back_populates="status_mappings")

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_status",
            "provider_reason_code",
            name="uq_courier_status_mappings_provider_status",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_courier_status_mappings_internal", "internal_status"),
    )
