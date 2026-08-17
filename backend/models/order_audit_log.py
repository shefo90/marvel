"""The Approach-A keystone.

Under Approach A the money lives in mutable columns on ``orders`` and
``order_items``, so this table is the *only* thing that makes section 11A's
requirement satisfiable:

    "All cost/value corrections must be auditable by order_id and timestamp so
    dashboards can be reconciled after returns, refunds, courier remittance or
    fee adjustments."

Three consequences the implementation must respect:

1. **Writes come from a database trigger, not from repositories.** A trigger on
   ``orders`` and ``order_items`` writes one row per changed money column. If
   this were application-level, a single repository function that forgot to log
   would break the chain silently — and nothing would fail.
2. **``old_value`` is load-bearing.** Section 6's Google Ads conversion
   adjustments need the *original* conversion value alongside the corrected one
   to issue a RETRACTION or RESTATEMENT. Under an append-only ledger that comes
   free; under Approach A it exists only because this column captured it. This
   is where Approach A is most likely to bite.
3. **Replay is the reconciliation path.** "What did net realized revenue look
   like on 12 August" is answered by replaying these rows backwards from the
   current column values. Deleting or compacting this table destroys that.

Numeric values are stored in a typed ``Numeric`` column *and* as text, so both
money corrections and non-numeric changes (status, provider reference) use one
table without losing precision or type.
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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ActorType, AuditAction


class OrderAuditLog(Base):
    __tablename__ = "order_audit_log"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Every row is keyed by order_id — section 11A's "auditable by order_id".
    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )

    # 'order' | 'order_item' | 'refund' | 'payment_transaction'
    entity = mapped_column(String(32), nullable=False)
    entity_id = mapped_column(BigInteger, nullable=True)
    action = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=16),
        nullable=False,
        server_default=AuditAction.update.value,
    )
    field = mapped_column(String(64), nullable=False)

    old_value = mapped_column(Text, nullable=True)
    new_value = mapped_column(Text, nullable=True)
    # Typed copies for money fields so reconciliation SQL needs no casting.
    old_amount = mapped_column(Numeric(12, 2), nullable=True)
    new_amount = mapped_column(Numeric(12, 2), nullable=True)
    is_monetary = mapped_column(String(1), nullable=True)

    reason = mapped_column(Text, nullable=True)
    actor_type = mapped_column(
        SAEnum(ActorType, native_enum=False, length=16),
        nullable=False,
        server_default=ActorType.system.value,
    )
    actor_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Which webhook/job/provider drove the change when no human did.
    source = mapped_column(String(64), nullable=True)
    source_reference = mapped_column(String(128), nullable=True)
    context = mapped_column(JSONB, nullable=False, server_default="{}")

    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order = relationship("Order", back_populates="audit_entries")
    actor_user = relationship("User", back_populates="order_audit_entries")

    __table_args__ = (
        CheckConstraint(
            "entity IN ('order','order_item','refund','payment_transaction')",
            name="ck_order_audit_log_entity",
        ),
        CheckConstraint(
            "(actor_type = 'staff') = (actor_user_id IS NOT NULL)",
            name="ck_order_audit_log_actor",
        ),
        # A change must actually change something.
        CheckConstraint(
            "old_value IS DISTINCT FROM new_value "
            "OR old_amount IS DISTINCT FROM new_amount",
            name="ck_order_audit_log_real_change",
        ),
        Index("ix_order_audit_log_order_id", "order_id", "occurred_at"),
        Index("ix_order_audit_log_occurred_at", "occurred_at"),
        Index("ix_order_audit_log_field", "entity", "field"),
        Index("ix_order_audit_log_actor_user_id", "actor_user_id"),
    )
