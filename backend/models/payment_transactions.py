"""One row per payment attempt.

A failed-then-retried card payment is two rows, not an overwritten status, so
section 9's "track failure reason category" is answerable per attempt.

Section 9 also warns: "do not expose sensitive details". Only a coarse
``failure_reason_category`` is stored — never the gateway's raw decline text,
never card data.
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
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import PaymentMethod, PaymentStatus
from models.mixins import TimestampMixin


class PaymentTransaction(Base, TimestampMixin):
    __tablename__ = "payment_transactions"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    provider = mapped_column(String(64), nullable=False)
    provider_transaction_id = mapped_column(String(128), nullable=True)
    method = mapped_column(
        SAEnum(PaymentMethod, native_enum=False, length=16), nullable=False
    )
    attempt_number = mapped_column(Integer, nullable=False, server_default="1")

    amount = mapped_column(Numeric(12, 2), nullable=False)
    currency = mapped_column(String(3), nullable=False, server_default="EGP")
    status = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=24),
        nullable=False,
        server_default=PaymentStatus.initiated.value,
    )
    failure_reason_category = mapped_column(String(64), nullable=True)

    initiated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)

    order = relationship("Order", back_populates="payment_transactions")

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_payment_transactions_provider_ref",
        ),
        UniqueConstraint(
            "order_id", "attempt_number", name="uq_payment_transactions_attempt"
        ),
        CheckConstraint("amount >= 0", name="ck_payment_transactions_amount"),
        CheckConstraint("currency = 'EGP'", name="ck_payment_transactions_currency"),
        CheckConstraint(
            "attempt_number > 0", name="ck_payment_transactions_attempt_positive"
        ),
        Index("ix_payment_transactions_order_id", "order_id"),
        Index("ix_payment_transactions_status", "status"),
    )
