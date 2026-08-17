"""Full and partial refunds.

Section 15: "Partial/full refund updates analytics and order ledger correctly."
A refund carries line-level detail in ``refund_items`` so a partial refund of
specific items is representable, which GA4's ``refund`` event needs in order to
send the affected ``items[]`` rather than only a value.

``logical_event_id`` is generated once here and reused by both the browser and
server copies of the refund event, and by section 6's Google Ads conversion
adjustment (RESTATEMENT for a corrected value, RETRACTION for a full reversal).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import RefundStatus
from models.mixins import TimestampMixin


class Refund(Base, TimestampMixin):
    __tablename__ = "refunds"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    refund_number = mapped_column(String(32), nullable=False)

    provider = mapped_column(String(64), nullable=True)
    provider_refund_id = mapped_column(String(128), nullable=True)

    amount = mapped_column(Numeric(12, 2), nullable=False)
    currency = mapped_column(String(3), nullable=False, server_default="EGP")
    # Fees the gateway returned with the refund, if any — feeds the profit ledger.
    gateway_fee_refunded = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    # Cost attributable to the return itself (courier return leg, restocking).
    return_cost = mapped_column(Numeric(12, 2), nullable=False, server_default="0")

    is_partial = mapped_column(Boolean, nullable=False, server_default="false")
    reason = mapped_column(String(64), nullable=True)
    notes = mapped_column(Text, nullable=True)
    status = mapped_column(
        SAEnum(RefundStatus, native_enum=False, length=16),
        nullable=False,
        server_default=RefundStatus.pending.value,
    )

    initiated_by_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    logical_event_id = mapped_column(String(128), nullable=True)

    requested_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)

    order = relationship("Order", back_populates="refunds")
    items = relationship(
        "RefundItem", back_populates="refund", cascade="all, delete-orphan"
    )
    initiated_by = relationship("User")

    __table_args__ = (
        UniqueConstraint("refund_number", name="uq_refunds_refund_number"),
        UniqueConstraint(
            "provider", "provider_refund_id", name="uq_refunds_provider_ref"
        ),
        UniqueConstraint("logical_event_id", name="uq_refunds_logical_event"),
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        CheckConstraint("currency = 'EGP'", name="ck_refunds_currency_egp"),
        CheckConstraint(
            "gateway_fee_refunded >= 0 AND return_cost >= 0",
            name="ck_refunds_costs_non_negative",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_refunds_completed",
        ),
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_status", "status"),
        Index("ix_refunds_requested_at", "requested_at"),
    )
