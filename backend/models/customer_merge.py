"""Audit trail for guest identity merges.

Section 11A: "Guest identity merging must use explicit, auditable rules."
``snapshot_before`` holds the losing customer's aggregates so a merge can be
reasoned about — and if necessary reversed — after the fact.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import ActorType, MergeRule


class CustomerMerge(Base):
    __tablename__ = "customer_merge"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    surviving_customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    merged_customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    match_rule = mapped_column(
        SAEnum(MergeRule, native_enum=False, length=24), nullable=False
    )
    matched_keys = mapped_column(JSONB, nullable=False, server_default="{}")
    actor_type = mapped_column(
        SAEnum(ActorType, native_enum=False, length=16), nullable=False
    )
    actor_user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason = mapped_column(Text, nullable=True)
    orders_moved_count = mapped_column(Integer, nullable=False, server_default="0")
    # Section 11A: first acquisition is never overwritten by a merge.
    acquisition_replaced = mapped_column(Boolean, nullable=False, server_default="false")
    snapshot_before = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    surviving_customer = relationship(
        "Customer", foreign_keys=[surviving_customer_id]
    )
    merged_customer = relationship("Customer", foreign_keys=[merged_customer_id])
    actor_user = relationship("User", back_populates="customer_merges")

    __table_args__ = (
        CheckConstraint(
            "surviving_customer_id <> merged_customer_id",
            name="ck_customer_merge_distinct",
        ),
        # A tombstone is created exactly once.
        UniqueConstraint("merged_customer_id", name="uq_customer_merge_merged_customer"),
        CheckConstraint(
            "(actor_type = 'staff') = (actor_user_id IS NOT NULL)",
            name="ck_customer_merge_actor",
        ),
        Index("ix_customer_merge_surviving", "surviving_customer_id"),
        Index("ix_customer_merge_occurred_at", "occurred_at"),
        Index("ix_customer_merge_actor_user_id", "actor_user_id"),
    )
