"""Server-side cart.

Section 14 lists ``POST/PATCH /cart``; section 4 is the real driver — the cart
is the durable carrier of attribution *before* an order exists, so the
acquisition history survives browser loss.

``checkout_idempotency_key`` is a cart-scoped DB-level guard that complements
the generic ``idempotency_keys`` table: even if two checkout requests race past
the application check, the unique constraint means only one can convert this
cart.

Caching note: cart reads are per-visitor and mutable — they must never be served
from the shared catalog cache.
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
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import CartStatus


class Cart(Base):
    __tablename__ = "carts"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Opaque token held by the browser. Anonymous carts have no customer.
    token = mapped_column(String(64), nullable=False)
    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    status = mapped_column(
        SAEnum(CartStatus, native_enum=False, length=16),
        nullable=False,
        server_default=CartStatus.active.value,
    )
    locale = mapped_column(String(5), nullable=False, server_default="en")
    currency = mapped_column(String(3), nullable=False, server_default="EGP")

    item_count = mapped_column(Integer, nullable=False, server_default="0")
    subtotal = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    discount_total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    coupon_code = mapped_column(String(64), nullable=True)

    checkout_idempotency_key = mapped_column(String(128), nullable=True)
    converted_order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    last_activity_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_at = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    customer = relationship("Customer", back_populates="carts")
    items = relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan"
    )
    mutations = relationship(
        "CartMutation", back_populates="cart", cascade="all, delete-orphan"
    )
    attribution = relationship(
        "CartAttribution",
        back_populates="cart",
        uselist=False,
        cascade="all, delete-orphan",
    )
    converted_order = relationship("Order", foreign_keys=[converted_order_id])

    __table_args__ = (
        UniqueConstraint("token", name="uq_carts_token"),
        UniqueConstraint(
            "checkout_idempotency_key", name="uq_carts_checkout_idempotency_key"
        ),
        CheckConstraint("currency = 'EGP'", name="ck_carts_currency_egp"),
        CheckConstraint("item_count >= 0", name="ck_carts_item_count_non_negative"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND total >= 0",
            name="ck_carts_amounts_non_negative",
        ),
        CheckConstraint(
            "(status = 'converted') = (converted_order_id IS NOT NULL)",
            name="ck_carts_converted_consistency",
        ),
        Index("ix_carts_customer_id", "customer_id"),
        Index(
            "ix_carts_active_expiry",
            "expires_at",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_carts_last_activity_at", "last_activity_at"),
    )
