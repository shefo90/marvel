"""Customer address book.

Egyptian address shape: governorate + city + district + street, with building /
floor / apartment / landmark, which is what couriers actually need. Postal codes
are optional because they are not reliably used in Egypt.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class Address(Base, TimestampMixin):
    __tablename__ = "addresses"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    label = mapped_column(String(50), nullable=True)
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
    is_default_shipping = mapped_column(Boolean, nullable=False, server_default="false")
    archived_at = mapped_column(DateTime(timezone=True), nullable=True)

    customer = relationship("Customer", back_populates="addresses")
    order_snapshots = relationship("OrderAddress", back_populates="source_address")

    __table_args__ = (
        CheckConstraint("char_length(phone) >= 8", name="ck_addresses_phone_length"),
        Index("ix_addresses_customer_id", "customer_id"),
        # At most one default shipping address per customer.
        Index(
            "uq_addresses_default_shipping",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default_shipping AND archived_at IS NULL"),
        ),
    )
