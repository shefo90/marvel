"""Append-only order lifecycle log.

Section 11A lists status history as an analytics-ready entity; section 13
requires an admin audit trail for manual status changes. This table serves the
lifecycle side — money corrections go to ``order_audit_log``.

``logical_event_id`` is generated at the state transition so S3/S5 can reuse it
as the deduplication key for the corresponding destination event, satisfying
section 15's "checkout events fire on actual state transition, not merely UI
button click".
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ActorType


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    # 'order' | 'payment' | 'cod' — which lifecycle this transition belongs to.
    dimension = mapped_column(String(16), nullable=False)
    from_status = mapped_column(String(32), nullable=True)
    to_status = mapped_column(String(32), nullable=False)

    actor_type = mapped_column(
        SAEnum(ActorType, native_enum=False, length=16), nullable=False
    )
    actor_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Which provider/webhook drove it, when it was not a human.
    source = mapped_column(String(64), nullable=True)
    source_reference = mapped_column(String(128), nullable=True)
    reason = mapped_column(Text, nullable=True)
    context = mapped_column(JSONB, nullable=False, server_default="{}")

    logical_event_id = mapped_column(String(128), nullable=True)
    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order = relationship("Order", back_populates="status_history")
    actor_user = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "logical_event_id", name="uq_order_status_history_logical_event"
        ),
        CheckConstraint(
            "dimension IN ('order','payment','cod')",
            name="ck_order_status_history_dimension",
        ),
        CheckConstraint(
            "(actor_type = 'staff') = (actor_user_id IS NOT NULL)",
            name="ck_order_status_history_actor",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_order_status_history_real_transition",
        ),
        Index("ix_order_status_history_order_id", "order_id", "occurred_at"),
        Index("ix_order_status_history_occurred_at", "occurred_at"),
        Index("ix_order_status_history_to_status", "dimension", "to_status"),
    )
