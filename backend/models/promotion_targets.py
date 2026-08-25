"""What a promotion applies to.

**A promotion with no target rows applies to nothing.** Discounting the whole
catalogue requires explicitly choosing ``all``, so a half-saved offer cannot
accidentally mark everything down — the failure mode of a default-to-everything
design is the one that costs real money.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import PromotionTargetType


class PromotionTarget(Base):
    __tablename__ = "promotion_targets"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promotion_id = mapped_column(
        BigInteger, ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False
    )
    target_type = mapped_column(
        SAEnum(PromotionTargetType, native_enum=False, length=16), nullable=False
    )
    # No foreign key: the column points at four different tables depending on
    # target_type, which no single FK can express. Resolution happens in
    # repositories/pricing.py, and a target whose row has gone simply matches
    # nothing.
    target_id = mapped_column(BigInteger, nullable=True)

    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    promotion = relationship("Promotion", back_populates="targets")

    __table_args__ = (
        CheckConstraint(
            "target_type IN ('all', 'product', 'variant', 'category', 'collection')",
            name="ck_promotion_targets_type",
        ),
        # 'all' carries no id; everything else must carry one. Either half
        # missing would be a target that matches nothing or everything by
        # accident.
        CheckConstraint(
            "(target_type = 'all' AND target_id IS NULL) "
            "OR (target_type <> 'all' AND target_id IS NOT NULL)",
            name="ck_promotion_targets_id_matches_type",
        ),
        UniqueConstraint(
            "promotion_id",
            "target_type",
            "target_id",
            name="uq_promotion_targets_unique",
            postgresql_nulls_not_distinct=True,
        ),
        # The pricing pass asks "which promotions target this product / variant /
        # category / collection", so the index is on the target, not the owner.
        Index("ix_promotion_targets_target", "target_type", "target_id"),
    )
