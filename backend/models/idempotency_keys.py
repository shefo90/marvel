"""Generic idempotency guard.

Section 13: "Idempotency keys for checkout/order creation and external webhook
processing." Section 15: "Purchase fires once after refresh/back navigation and
has stable transaction_id", and "Duplicate gateway/courier webhooks do not
duplicate conversions or state transitions."

Contract: a request presents a key. The first request inserts the row in the
same transaction as the work and stores the response. A replay finds the row and
returns the stored response verbatim — it never re-executes. A key seen while
the first request is still in flight (``status='in_progress'``) gets a 409, so
two concurrent submissions cannot both proceed.

``expires_at`` defaults to 24h (IDEMPOTENCY_TTL_HOURS). Design open question 5:
this must be confirmed against the payment gateway's retry horizon — a window
shorter than that horizon would let a very late gateway retry slip past replay
protection and duplicate an order.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Namespaced so an order key and a webhook key can never collide.
    scope = mapped_column(String(64), nullable=False)
    key = mapped_column(String(128), nullable=False)

    status = mapped_column(String(16), nullable=False, server_default="in_progress")
    # Hash of the request body: the same key with a different payload is a
    # client bug and must be rejected, not silently served the old response.
    request_fingerprint = mapped_column(String(64), nullable=True)

    response_status = mapped_column(Integer, nullable=True)
    response_body = mapped_column(JSONB, nullable=True)

    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    last_error = mapped_column(Text, nullable=True)

    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)

    order = relationship("Order")

    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_keys_scope_key"),
        CheckConstraint(
            "status IN ('in_progress','completed','failed')",
            name="ck_idempotency_keys_status",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_idempotency_keys_completed",
        ),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
        Index("ix_idempotency_keys_order_id", "order_id"),
    )
