"""Append-only log of every cart change.

Two jobs:

* **Idempotency.** ``idempotency_key`` is unique per cart, so a retried
  add-to-cart from a flaky mobile connection cannot double the quantity —
  section 15's rapid-repeated-clicks test.
* **Event fidelity.** ``logical_event_id`` is the id S3 will reuse for the
  browser and server copies of the corresponding ``add_to_cart`` /
  ``remove_from_cart`` event. Generating it here — at the actual state
  transition — is what makes section 15's "checkout events fire on actual state
  transition, not merely UI button click" achievable.
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
from core.enums import ActorType


class CartMutation(Base):
    __tablename__ = "cart_mutations"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cart_id = mapped_column(
        BigInteger, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key = mapped_column(String(128), nullable=True)
    mutation_type = mapped_column(String(32), nullable=False)
    variant_id = mapped_column(
        BigInteger,
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    quantity_delta = mapped_column(Integer, nullable=True)
    quantity_after = mapped_column(Integer, nullable=True)
    unit_price_at_mutation = mapped_column(Numeric(12, 2), nullable=True)
    value_delta = mapped_column(Numeric(12, 2), nullable=True)
    # Reused by S3/S5 as the deduplication key for this logical event.
    logical_event_id = mapped_column(String(128), nullable=True)
    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type = mapped_column(
        SAEnum(ActorType, native_enum=False, length=16),
        nullable=False,
        server_default=ActorType.customer.value,
    )
    actor_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    cart = relationship("Cart", back_populates="mutations")

    __table_args__ = (
        UniqueConstraint(
            "cart_id", "idempotency_key", name="uq_cart_mutations_idempotency"
        ),
        UniqueConstraint("logical_event_id", name="uq_cart_mutations_logical_event"),
        CheckConstraint(
            "mutation_type IN ('add','remove','update_quantity','clear',"
            "'apply_coupon','remove_coupon','merge','reprice','convert')",
            name="ck_cart_mutations_type",
        ),
        CheckConstraint(
            "quantity_after IS NULL OR quantity_after >= 0",
            name="ck_cart_mutations_quantity_after",
        ),
        Index("ix_cart_mutations_cart_id", "cart_id", "occurred_at"),
        Index("ix_cart_mutations_occurred_at", "occurred_at"),
    )
