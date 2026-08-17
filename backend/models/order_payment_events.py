"""Append-only payment event stream — section 9's state/event table.

``order_created``, ``payment_initiated``, ``payment_succeeded``,
``payment_failed``, ``purchase``, ``refund``.

``provider_event_id`` is uniquely constrained so a duplicate webhook delivery
cannot create a second event: section 9's "Every payment/shipping webhook
handler must be idempotent. The same provider webhook can arrive more than once;
duplicate delivery must not create duplicate orders, conversions or refunds."

The webhook *ingest* table itself is S4; this is the normalized event the ingest
writes into.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class OrderPaymentEvent(Base):
    __tablename__ = "order_payment_events"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    event_type = mapped_column(String(32), nullable=False)
    provider = mapped_column(String(64), nullable=True)
    provider_event_id = mapped_column(String(128), nullable=True)
    amount = mapped_column(Numeric(12, 2), nullable=True)
    currency = mapped_column(String(3), nullable=True)
    # Reused by S3/S5 as the destination deduplication key.
    logical_event_id = mapped_column(String(128), nullable=True)
    context = mapped_column(JSONB, nullable=False, server_default="{}")

    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order = relationship("Order", back_populates="payment_events")

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_order_payment_events_provider_ref"
        ),
        UniqueConstraint(
            "logical_event_id", name="uq_order_payment_events_logical_event"
        ),
        CheckConstraint(
            "event_type IN ('order_created','payment_initiated','payment_succeeded',"
            "'payment_failed','purchase','refund')",
            name="ck_order_payment_events_type",
        ),
        Index("ix_order_payment_events_order_id", "order_id", "occurred_at"),
        Index("ix_order_payment_events_type", "event_type", "occurred_at"),
    )
