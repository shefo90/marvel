"""Deterministic match keys for guest identity resolution.

Section 11A: "Guest identity merging must use explicit, auditable rules." This
table *is* the explicit rule — a normalized email or phone maps to exactly one
customer, so order-time resolution is a race-safe
``INSERT ... ON CONFLICT DO UPDATE`` rather than a read-then-write.

``value_sha256`` allows reverse lookup from an ad-platform/CAPI payload back to
a customer (sections 6 and 7) without putting raw PII in the query.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import IdentitySource, IdentityType


class CustomerIdentity(Base):
    __tablename__ = "customer_identity"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    identity_type = mapped_column(
        SAEnum(IdentityType, native_enum=False, length=16), nullable=False
    )
    value_normalized = mapped_column(String(320), nullable=True)
    value_sha256 = mapped_column(String(64), nullable=False)
    source = mapped_column(
        SAEnum(IdentitySource, native_enum=False, length=16), nullable=False
    )
    is_primary = mapped_column(Boolean, nullable=False, server_default="false")
    verified_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer = relationship("Customer", back_populates="identities")

    __table_args__ = (
        UniqueConstraint(
            "identity_type", "value_normalized", name="uq_customer_identity_value"
        ),
        CheckConstraint(
            "char_length(value_sha256) = 64", name="ck_customer_identity_sha256_len"
        ),
        # At most one current email and one current phone per customer.
        Index(
            "uq_customer_identity_primary",
            "customer_id",
            "identity_type",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        Index("ix_customer_identity_customer_id", "customer_id"),
        Index("ix_customer_identity_value_sha256", "value_sha256"),
    )
