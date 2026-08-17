"""The commerce order header, and under Approach A the order-level profit ledger.

``order_number`` is section 2's immutable commerce identity and doubles as the
GA4 / Google Ads ``transaction_id``. It is generated once and never regenerated
— a BEFORE UPDATE trigger added in the migration raises on any attempt to change
it, which makes section 2's rule unfalsifiable rather than merely documented.

**Approach A discipline.** Every money column here is mutable, and every
mutation MUST write an ``order_audit_log`` row. That is enforced by a database
trigger, not by application convention: if auditing lived in the repository
layer, one function that forgot it would silently destroy section 11A's audit
chain with nothing failing loudly.

``net_realized_revenue`` and ``contribution_profit`` are stored but **derived**.
A scheduled reconciliation job recomputes them independently and alerts on
divergence (section 13). Do not treat them as authoritative without that job.

VAT posture: prices are VAT-inclusive, so ``tax_total`` stays 0 and VAT is
derived for accounting. This matches section 5's example payload, which shows
``tax: 0``.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import (
    CodCollectionStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


class Order(Base):
    __tablename__ = "orders"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Section 2: unique, immutable, human-readable (e.g. ORD-100245).
    order_number = mapped_column(String(32), nullable=False)

    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True
    )
    cart_id = mapped_column(
        BigInteger, ForeignKey("carts.id", ondelete="SET NULL"), nullable=True
    )

    status = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=24),
        nullable=False,
        server_default=OrderStatus.pending.value,
    )
    locale = mapped_column(String(5), nullable=False, server_default="en")
    currency = mapped_column(String(3), nullable=False, server_default="EGP")

    # --- Section 3 order totals ------------------------------------------
    subtotal = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    tax_total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    shipping = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    # Value at order creation — section 11's "Gross ordered revenue". Frozen.
    gross_order_value = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    coupon_code = mapped_column(String(64), nullable=True)

    # --- Payment (section 3, section 9) -----------------------------------
    payment_status = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=24),
        nullable=False,
        server_default=PaymentStatus.pending.value,
    )
    payment_method = mapped_column(
        SAEnum(PaymentMethod, native_enum=False, length=16), nullable=True
    )
    payment_provider = mapped_column(String(64), nullable=True)
    gateway_transaction_id = mapped_column(String(128), nullable=True)
    payment_initiated_at = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at = mapped_column(DateTime(timezone=True), nullable=True)
    # Section 9: category only. Never the gateway's raw sensitive detail.
    payment_failure_reason_category = mapped_column(String(64), nullable=True)
    # Section 9: purchase fires once, idempotent by transaction_id/order_id.
    purchase_confirmed_at = mapped_column(DateTime(timezone=True), nullable=True)

    # --- COD money movement (section 3, section 10, section 11) -----------
    cod_amount = mapped_column(Numeric(12, 2), nullable=True)
    cod_collection_status = mapped_column(
        SAEnum(CodCollectionStatus, native_enum=False, length=16), nullable=True
    )
    cod_collected_at = mapped_column(DateTime(timezone=True), nullable=True)
    cod_remitted_amount = mapped_column(Numeric(12, 2), nullable=True)
    cod_remitted_at = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Section 11A profit ledger ----------------------------------------
    items_cogs_total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    promotion_cost_total = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    shipping_cost = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    cod_fee = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    gateway_fee = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    return_cost_total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    refunded_amount_total = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    last_refunded_at = mapped_column(DateTime(timezone=True), nullable=True)
    # Derived. Recomputed by the reconciliation job; never trusted blindly.
    net_realized_revenue = mapped_column(Numeric(12, 2), nullable=True)
    contribution_profit = mapped_column(Numeric(12, 2), nullable=True)

    # --- Section 6: server-derived, never inferred from a browser cookie ---
    is_new_customer = mapped_column(Boolean, nullable=True)

    # Business-timezone date for reporting; timestamps stay UTC (section 11A).
    business_date = mapped_column(Date, nullable=True)
    placed_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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

    customer = relationship("Customer", back_populates="orders")
    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    attribution = relationship(
        "OrderAttribution",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )
    addresses = relationship(
        "OrderAddress",
        back_populates="order",
        cascade="all, delete-orphan",
        foreign_keys="OrderAddress.order_id",
    )
    status_history = relationship(
        "OrderStatusHistory", back_populates="order", cascade="all, delete-orphan"
    )
    audit_entries = relationship(
        "OrderAuditLog", back_populates="order", cascade="all, delete-orphan"
    )
    payment_transactions = relationship(
        "PaymentTransaction", back_populates="order", cascade="all, delete-orphan"
    )
    payment_events = relationship(
        "OrderPaymentEvent", back_populates="order", cascade="all, delete-orphan"
    )
    refunds = relationship(
        "Refund", back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("order_number", name="uq_orders_order_number"),
        CheckConstraint("currency = 'EGP'", name="ck_orders_currency_egp"),
        # COD fields are present exactly when the method is COD.
        CheckConstraint(
            "(payment_method = 'cod') = "
            "(cod_amount IS NOT NULL AND cod_collection_status IS NOT NULL)",
            name="ck_orders_cod_fields_consistent",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND tax_total >= 0 AND shipping >= 0 "
            "AND total >= 0 AND gross_order_value >= 0",
            name="ck_orders_amounts_non_negative",
        ),
        CheckConstraint(
            "items_cogs_total >= 0 AND promotion_cost_total >= 0 "
            "AND shipping_cost >= 0 AND cod_fee >= 0 AND gateway_fee >= 0 "
            "AND return_cost_total >= 0 AND refunded_amount_total >= 0",
            name="ck_orders_costs_non_negative",
        ),
        CheckConstraint(
            "refunded_amount_total <= total", name="ck_orders_refund_within_total"
        ),
        # The totals identity. VAT-inclusive, so tax_total participates at 0.
        CheckConstraint(
            "total = subtotal - discount + tax_total + shipping",
            name="ck_orders_total_identity",
        ),
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_status", "status"),
        Index("ix_orders_payment_status", "payment_status"),
        Index("ix_orders_placed_at", "placed_at"),
        Index("ix_orders_business_date", "business_date"),
        # Section 11 funnel + section 13 reconciliation scans.
        Index(
            "ix_orders_cod_outstanding",
            "cod_collection_status",
            postgresql_where=text("payment_method = 'cod'"),
        ),
    )
