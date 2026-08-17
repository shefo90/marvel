"""Immutable address snapshot taken at checkout.

Resolves design open question 1 in favour of the order owning the address:
the delivery address is part of what was agreed at checkout, so editing the
customer's address book must never silently rewrite where a placed order ships,
and a re-shipment must not either.

Address fields are **write-once**. A correction does not UPDATE them — it
inserts a replacement row and stamps ``superseded_at``/``superseded_by_id`` on
the old one, so the original remains readable (section 11A's snapshot rule and
section 13's admin audit trail).
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
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import AddressType


class OrderAddress(Base):
    __tablename__ = "order_addresses"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    address_type = mapped_column(
        SAEnum(AddressType, native_enum=False, length=16), nullable=False
    )
    source_address_id = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )

    recipient_name = mapped_column(String(150), nullable=False)
    phone = mapped_column(String(20), nullable=False)
    phone_alt = mapped_column(String(20), nullable=True)
    governorate = mapped_column(String(64), nullable=False)
    city = mapped_column(String(100), nullable=False)
    district = mapped_column(String(100), nullable=True)
    street_address = mapped_column(Text, nullable=False)
    building = mapped_column(String(50), nullable=True)
    floor = mapped_column(String(20), nullable=True)
    apartment = mapped_column(String(20), nullable=True)
    landmark = mapped_column(Text, nullable=True)
    postal_code = mapped_column(String(20), nullable=True)
    country_code = mapped_column(String(2), nullable=False, server_default="EG")

    captured_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id = mapped_column(
        BigInteger, ForeignKey("order_addresses.id", ondelete="SET NULL"), nullable=True
    )
    corrected_by_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order = relationship("Order", back_populates="addresses")
    source_address = relationship("Address", back_populates="order_snapshots")
    superseded_by = relationship(
        "OrderAddress", remote_side=[id], back_populates="supersedes"
    )
    supersedes = relationship("OrderAddress", back_populates="superseded_by")

    __table_args__ = (
        # A supersession always names its replacement.
        CheckConstraint(
            "(superseded_at IS NULL) = (superseded_by_id IS NULL)",
            name="ck_order_addresses_supersede_pair",
        ),
        Index("ix_order_addresses_order_id", "order_id"),
        # Exactly one live shipping and one live billing snapshot per order.
        Index(
            "uq_order_addresses_active",
            "order_id",
            "address_type",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_order_addresses_superseded_by", "superseded_by_id"),
    )
