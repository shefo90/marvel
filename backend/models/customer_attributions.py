"""Preserved first acquisition plus the latest touch, per customer.

This table is the single place section 11A's rule is enforced:

    "Do not overwrite first acquisition when a returning customer comes through
    a new campaign."

``first_touch_*`` is written once and stamped with ``first_touch_locked_at``.
The repository layer refuses to update a locked row; the denormalized
source/medium/campaign columns exist so cohort and CAC:LTV reporting can group
without joining back through ``attribution_touches``.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class CustomerAttribution(Base):
    __tablename__ = "customer_attributions"

    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )

    # --- Write-once first touch ------------------------------------------
    first_touch_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_touches.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_touch_at = mapped_column(DateTime(timezone=True), nullable=True)
    first_touch_locked_at = mapped_column(DateTime(timezone=True), nullable=True)
    first_touch_source = mapped_column(String(255), nullable=True)
    first_touch_medium = mapped_column(String(255), nullable=True)
    first_touch_campaign = mapped_column(String(255), nullable=True)
    first_touch_channel_group = mapped_column(String(64), nullable=True)

    # --- Mutable latest touch --------------------------------------------
    last_touch_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_touches.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_touch_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_touch_source = mapped_column(String(255), nullable=True)
    last_touch_medium = mapped_column(String(255), nullable=True)
    last_touch_campaign = mapped_column(String(255), nullable=True)
    last_touch_channel_group = mapped_column(String(64), nullable=True)

    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    customer = relationship("Customer", back_populates="attribution")
    first_touch = relationship("AttributionTouch", foreign_keys=[first_touch_id])
    last_touch = relationship("AttributionTouch", foreign_keys=[last_touch_id])

    __table_args__ = (
        CheckConstraint(
            "(first_touch_id IS NULL) = (first_touch_locked_at IS NULL)",
            name="ck_customer_attributions_first_touch_stamped",
        ),
        Index("ix_customer_attributions_first_touch", "first_touch_source", "first_touch_campaign"),
    )
