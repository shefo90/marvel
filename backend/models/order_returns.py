"""A return or failed delivery coming back from the courier.

Kept separate from ``refunds``: a parcel can come back without money moving
(failed delivery, refused on doorstep), and money can move without a parcel
coming back (goodwill refund). Section 7 makes the same distinction for the
``OrderReturned/Cancelled`` signal — "Keep separate from Purchase; reconcile
business revenue internally".

Schema-only in S1.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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
from models.mixins import TimestampMixin


class OrderReturn(Base, TimestampMixin):
    __tablename__ = "order_returns"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id = mapped_column(
        BigInteger, ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True
    )
    refund_id = mapped_column(
        BigInteger, ForeignKey("refunds.id", ondelete="SET NULL"), nullable=True
    )
    return_number = mapped_column(String(32), nullable=False)

    # 'customer_refused' | 'failed_delivery' | 'customer_request' | 'damaged' | ...
    reason = mapped_column(String(64), nullable=True)
    reason_detail = mapped_column(Text, nullable=True)
    status = mapped_column(String(32), nullable=False, server_default="initiated")

    # Cost of the return leg — feeds orders.return_cost_total (section 11A).
    return_shipping_cost = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    restocking_cost = mapped_column(Numeric(12, 2), nullable=False, server_default="0")

    initiated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    received_at = mapped_column(DateTime(timezone=True), nullable=True)
    initiated_by_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    logical_event_id = mapped_column(String(128), nullable=True)

    order = relationship("Order")
    shipment = relationship("Shipment")
    refund = relationship("Refund")
    items = relationship(
        "OrderReturnItem", back_populates="order_return", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("return_number", name="uq_order_returns_return_number"),
        UniqueConstraint("logical_event_id", name="uq_order_returns_logical_event"),
        CheckConstraint(
            "status IN ('initiated','in_transit','received','restocked','cancelled')",
            name="ck_order_returns_status",
        ),
        CheckConstraint(
            "return_shipping_cost >= 0 AND restocking_cost >= 0",
            name="ck_order_returns_costs_non_negative",
        ),
        Index("ix_order_returns_order_id", "order_id"),
        Index("ix_order_returns_status", "status"),
    )
