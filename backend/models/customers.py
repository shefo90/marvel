"""Customer master — the analytics/commerce identity for a shopper.

A row exists for every order, guest or not (design section 2). ``id`` is the
internal, non-PII ``customer_id`` of section 2 and is never sent to the browser;
``public_id`` is the opaque UUID used where an external reference is needed
(section 7's ``external_id``).

The lifetime aggregates are section 11A's customer layer. They are **derived**
and recomputed from authoritative order history — never incremented ad hoc from
a browser event, per section 6's "do not infer it only from a browser cookie".
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import CustomerStatus
from models.mixins import TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id = mapped_column(
        UUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")
    )
    status = mapped_column(
        SAEnum(CustomerStatus, native_enum=False, length=16),
        nullable=False,
        server_default=CustomerStatus.active.value,
    )

    email = mapped_column(String(320), nullable=True)
    phone = mapped_column(String(32), nullable=True)
    first_name = mapped_column(String(100), nullable=True)
    last_name = mapped_column(String(100), nullable=True)

    merged_into_customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True
    )
    merged_at = mapped_column(DateTime(timezone=True), nullable=True)
    anonymized_at = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Section 11A customer & lifetime-value layer ----------------------
    first_order_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_order_at = mapped_column(DateTime(timezone=True), nullable=True)
    first_delivered_order_at = mapped_column(DateTime(timezone=True), nullable=True)
    orders_count = mapped_column(Integer, nullable=False, server_default="0")
    delivered_orders_count = mapped_column(Integer, nullable=False, server_default="0")
    lifetime_gross_ordered_revenue = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    lifetime_delivered_revenue = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    lifetime_net_revenue = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    lifetime_contribution_profit = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    aggregates_recomputed_at = mapped_column(DateTime(timezone=True), nullable=True)

    identities = relationship(
        "CustomerIdentity", back_populates="customer", cascade="all, delete-orphan"
    )
    credential = relationship(
        "CustomerCredential",
        back_populates="customer",
        uselist=False,
        cascade="all, delete-orphan",
    )
    refresh_tokens = relationship(
        "CustomerRefreshToken", back_populates="customer", cascade="all, delete-orphan"
    )
    attribution = relationship(
        "CustomerAttribution", back_populates="customer", uselist=False
    )
    addresses = relationship("Address", back_populates="customer")
    orders = relationship("Order", back_populates="customer")
    carts = relationship("Cart", back_populates="customer")
    merged_into = relationship(
        "Customer", remote_side=[id], back_populates="merged_children"
    )
    merged_children = relationship("Customer", back_populates="merged_into")

    __table_args__ = (
        UniqueConstraint("public_id", name="uq_customers_public_id"),
        # Section 4 needs an email/phone handle to associate history across
        # sessions; anonymized rows are exempt under section 12 retention rules.
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL OR status = 'anonymized'",
            name="ck_customers_contact_present",
        ),
        CheckConstraint(
            "merged_into_customer_id IS NULL OR merged_into_customer_id <> id",
            name="ck_customers_no_self_merge",
        ),
        CheckConstraint(
            "(merged_into_customer_id IS NULL AND merged_at IS NULL) "
            "OR (merged_into_customer_id IS NOT NULL AND merged_at IS NOT NULL "
            "AND status = 'merged')",
            name="ck_customers_merge_consistency",
        ),
        # Section 11 funnel invariant: Delivered is a subset of Orders.
        CheckConstraint(
            "orders_count >= 0 AND delivered_orders_count >= 0 "
            "AND delivered_orders_count <= orders_count",
            name="ck_customers_counts_sane",
        ),
        Index("ix_customers_merged_into", "merged_into_customer_id"),
        Index("ix_customers_first_order_at", "first_order_at"),
        Index("ix_customers_created_at", "created_at"),
        Index(
            "ix_customers_status", "status", postgresql_where=text("status <> 'active'")
        ),
    )
