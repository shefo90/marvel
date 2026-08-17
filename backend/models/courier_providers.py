"""Registered courier integrations.

Section 10: "Build a courier abstraction rather than Bosta-specific business
logic throughout the codebase. Bosta can be the first adapter; another courier
can be added later without changing the order model or tracking contract."

A row here is a provider registration; the adapter implementing
``CourierProvider`` (create_shipment / cancel_shipment / get_tracking /
handle_webhook / normalize_status) is resolved by ``code``. Business code never
names Bosta.

Schema-only in S1 — S4 wires the adapters.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class CourierProvider(Base, TimestampMixin):
    __tablename__ = "courier_providers"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code = mapped_column(String(32), nullable=False)
    name = mapped_column(String(120), nullable=False)
    is_active = mapped_column(Boolean, nullable=False, server_default="true")
    supports_webhooks = mapped_column(Boolean, nullable=False, server_default="true")
    # Section 10: "If the selected courier does not offer the required webhook,
    # implement scheduled status polling + reconciliation as fallback."
    supports_polling = mapped_column(Boolean, nullable=False, server_default="false")
    supports_cod = mapped_column(Boolean, nullable=False, server_default="true")
    # Section 13: webhook signature verification. The secret itself lives in the
    # environment/secret manager, never here — this only records the scheme.
    signature_scheme = mapped_column(String(32), nullable=True)
    config = mapped_column(JSONB, nullable=False, server_default="{}")

    status_mappings = relationship(
        "CourierStatusMapping", back_populates="provider", cascade="all, delete-orphan"
    )
    shipments = relationship("Shipment", back_populates="provider")

    __table_args__ = (
        UniqueConstraint("code", name="uq_courier_providers_code"),
        CheckConstraint(r"code ~ '^[a-z0-9_]+$'", name="ck_courier_providers_code"),
        Index("ix_courier_providers_active", "is_active"),
    )
