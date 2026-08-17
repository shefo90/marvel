"""Line-level refund detail.

Lets GA4's ``refund`` event carry the affected ``items[]`` rather than only a
total, and lets the profit ledger reduce the right line's realized revenue and
restock the right variant.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class RefundItem(Base):
    __tablename__ = "refund_items"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    refund_id = mapped_column(
        BigInteger, ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id = mapped_column(
        BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity = mapped_column(Integer, nullable=False)
    amount = mapped_column(Numeric(12, 2), nullable=False)
    restocked = mapped_column(Boolean, nullable=False, server_default="false")

    refund = relationship("Refund", back_populates="items")
    order_item = relationship("OrderItem", back_populates="refund_items")

    __table_args__ = (
        UniqueConstraint("refund_id", "order_item_id", name="uq_refund_items_line"),
        CheckConstraint("quantity > 0", name="ck_refund_items_quantity_positive"),
        CheckConstraint("amount >= 0", name="ck_refund_items_amount_non_negative"),
        Index("ix_refund_items_order_item_id", "order_item_id"),
    )
