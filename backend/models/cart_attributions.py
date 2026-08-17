"""Attribution carried by a server-side cart.

Section 4: "When the shopper provides an email/phone or creates an order,
associate the allowed attribution data with the server-side cart/order record so
the history survives browser loss where legally permitted."

This is the bridge between an anonymous visitor's touches and the order snapshot
that section 15 requires to survive landing -> navigation -> checkout.
"""

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class CartAttribution(Base):
    __tablename__ = "cart_attributions"

    cart_id = mapped_column(
        BigInteger, ForeignKey("carts.id", ondelete="CASCADE"), primary_key=True
    )
    visitor_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_visitors.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_touch_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_touches.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_touch_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_touches.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    cart = relationship("Cart", back_populates="attribution")
    first_touch = relationship("AttributionTouch", foreign_keys=[first_touch_id])
    last_touch = relationship("AttributionTouch", foreign_keys=[last_touch_id])

    __table_args__ = (Index("ix_cart_attributions_visitor_id", "visitor_id"),)
