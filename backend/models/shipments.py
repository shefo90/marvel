"""A parcel handed to a courier.

Carries section 3's fulfilment field set: courier_provider, shipment_id,
tracking_number, shipping_cost, fulfilment timestamps, delivery_status,
delivered_at, failed_delivery_reason, return_reason, returned_at.

One order has at most one live shipment. For a single-warehouse Egyptian
footwear retailer, split fulfilment is not a real scenario, and modelling it
speculatively would complicate the section 11 funnel (Shipped / Delivered /
Delivery rate) for no current benefit. Multiple *rows* per order are still
allowed so a cancelled-and-reissued shipment has history; the partial unique
index is what keeps exactly one active.

Schema-only in S1 — S4 wires the adapters and webhooks.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ShipmentStatus
from models.mixins import TimestampMixin


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipments"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    order_address_id = mapped_column(
        BigInteger, ForeignKey("order_addresses.id", ondelete="RESTRICT"), nullable=True
    )
    provider_id = mapped_column(
        BigInteger, ForeignKey("courier_providers.id", ondelete="RESTRICT"), nullable=False
    )

    # The courier's own identifier for this parcel.
    provider_shipment_id = mapped_column(String(128), nullable=True)
    tracking_number = mapped_column(String(128), nullable=True)
    tracking_url = mapped_column(Text, nullable=True)

    status = mapped_column(
        SAEnum(ShipmentStatus, native_enum=False, length=32),
        nullable=False,
        server_default=ShipmentStatus.shipment_created.value,
    )
    is_active = mapped_column(
        # False once cancelled or superseded by a reissued shipment.
        String(1), nullable=False, server_default="Y"
    )

    # --- Money ------------------------------------------------------------
    shipping_cost = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    cod_amount = mapped_column(Numeric(12, 2), nullable=True)
    cod_collected_at = mapped_column(DateTime(timezone=True), nullable=True)
    cod_remitted_at = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Fulfilment timestamps (section 3) --------------------------------
    created_with_courier_at = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at = mapped_column(DateTime(timezone=True), nullable=True)
    out_for_delivery_at = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at = mapped_column(DateTime(timezone=True), nullable=True)
    failed_delivery_reason = mapped_column(String(255), nullable=True)
    return_reason = mapped_column(String(255), nullable=True)
    returned_at = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at = mapped_column(DateTime(timezone=True), nullable=True)

    # Last raw provider status seen, for audit against the normalized value.
    last_provider_status = mapped_column(String(128), nullable=True)
    last_synced_at = mapped_column(DateTime(timezone=True), nullable=True)
    context = mapped_column(JSONB, nullable=False, server_default="{}")

    order = relationship("Order")
    provider = relationship("CourierProvider", back_populates="shipments")
    order_address = relationship("OrderAddress")
    status_events = relationship(
        "ShipmentStatusEvent", back_populates="shipment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_shipment_id",
            name="uq_shipments_provider_shipment_id",
        ),
        CheckConstraint("shipping_cost >= 0", name="ck_shipments_shipping_cost"),
        CheckConstraint("is_active IN ('Y','N')", name="ck_shipments_is_active"),
        CheckConstraint(
            "cod_amount IS NULL OR cod_amount >= 0", name="ck_shipments_cod_amount"
        ),
        # Exactly one live shipment per order.
        Index(
            "uq_shipments_active_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("is_active = 'Y'"),
        ),
        Index("ix_shipments_order_id", "order_id"),
        Index("ix_shipments_status", "status"),
        Index("ix_shipments_tracking_number", "tracking_number"),
        # Section 13: alert on shipments with no courier update.
        Index("ix_shipments_last_synced_at", "last_synced_at"),
    )
