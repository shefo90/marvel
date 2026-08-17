"""Append-only normalized shipment status history.

Section 10 requires storing "provider event ID/raw-status reference and
processed timestamp for deduplication/audit". ``provider_event_id`` is uniquely
constrained per provider, so a redelivered courier webhook cannot create a
second transition — section 15's "duplicate gateway/courier webhooks do not
duplicate conversions or state transitions".

``raw_provider_status`` is kept alongside the normalized value so a mis-mapping
is diagnosable after the fact rather than lost.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ShipmentStatus


class ShipmentStatusEvent(Base):
    __tablename__ = "shipment_status_events"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shipment_id = mapped_column(
        BigInteger, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    provider_id = mapped_column(
        BigInteger, ForeignKey("courier_providers.id", ondelete="RESTRICT"), nullable=False
    )
    provider_event_id = mapped_column(String(128), nullable=True)

    raw_provider_status = mapped_column(String(128), nullable=True)
    status = mapped_column(
        SAEnum(ShipmentStatus, native_enum=False, length=32), nullable=False
    )
    reason = mapped_column(String(255), nullable=True)
    location = mapped_column(String(255), nullable=True)
    # Set when the raw status had no mapping row — surfaces silent drift.
    is_unmapped = mapped_column(Boolean, nullable=False, server_default=text("false"))

    logical_event_id = mapped_column(String(128), nullable=True)
    payload = mapped_column(JSONB, nullable=False, server_default="{}")

    occurred_at = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    shipment = relationship("Shipment", back_populates="status_events")

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_event_id",
            name="uq_shipment_status_events_provider_event",
        ),
        UniqueConstraint(
            "logical_event_id", name="uq_shipment_status_events_logical_event"
        ),
        Index("ix_shipment_status_events_shipment_id", "shipment_id", "occurred_at"),
        Index("ix_shipment_status_events_status", "status", "occurred_at"),
    )
