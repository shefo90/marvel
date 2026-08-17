"""Which lines came back, and how many."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class OrderReturnItem(Base):
    __tablename__ = "order_return_items"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_return_id = mapped_column(
        BigInteger, ForeignKey("order_returns.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id = mapped_column(
        BigInteger, ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity = mapped_column(Integer, nullable=False)
    condition = mapped_column(String(32), nullable=True)
    restocked = mapped_column(Boolean, nullable=False, server_default="false")

    order_return = relationship("OrderReturn", back_populates="items")
    order_item = relationship("OrderItem")

    __table_args__ = (
        UniqueConstraint(
            "order_return_id", "order_item_id", name="uq_order_return_items_line"
        ),
        CheckConstraint("quantity > 0", name="ck_order_return_items_quantity_positive"),
        CheckConstraint(
            "condition IS NULL OR condition IN ('sellable','damaged','unknown')",
            name="ck_order_return_items_condition",
        ),
        Index("ix_order_return_items_order_item_id", "order_item_id"),
    )
