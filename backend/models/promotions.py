"""Operator-chosen offers.

Deliberately not a rules engine. The original S1b design had rule priority,
stacking resolution and tiered thresholds; this replaces it with "the operator
decides, and the system records what they chose". Roughly a quarter of the work,
with every measurement obligation intact.

The value columns are tied to ``type`` by CHECK constraints rather than by
convention, so a percentage promotion cannot carry a fixed amount and a BOGO
cannot be saved without its quantities. That matters because these rows price
real baskets: a half-specified promotion is not a validation nicety, it is a
wrong number on someone's order.

There is no ``priority`` column and no ``promotion_redemptions`` table. With
best-single-discount-wins and no coupon codes, redemption counts are a query
over ``order_items``; storing a derivable number invites it to disagree with the
orders it summarises.
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
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import PromotionType
from models.mixins import TimestampMixin


class Promotion(Base, TimestampMixin):
    __tablename__ = "promotions"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # The operator's own label, e.g. "Eid 30% off sandals". Shown in the
    # back-office and nowhere else; the shopper sees a price, not a campaign.
    name = mapped_column(String(160), nullable=False)
    type = mapped_column(SAEnum(PromotionType, native_enum=False, length=16), nullable=False)

    discount_percent = mapped_column(Numeric(5, 2), nullable=True)
    discount_amount = mapped_column(Numeric(12, 2), nullable=True)

    buy_quantity = mapped_column(Integer, nullable=True)
    get_quantity = mapped_column(Integer, nullable=True)
    # 100 means the "get" units are free. Anything less is a partial discount on
    # them, which is what makes "buy 2 get 1 half price" expressible.
    get_discount_percent = mapped_column(Numeric(5, 2), nullable=True)

    starts_at = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at = mapped_column(DateTime(timezone=True), nullable=True)
    # The operator's on/off switch, independent of the window. Turning a
    # promotion off must not require editing its dates.
    is_active = mapped_column(Boolean, nullable=False, server_default="true")

    created_by_user_id = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    targets = relationship(
        "PromotionTarget", back_populates="promotion", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('percentage', 'fixed', 'bogo')", name="ck_promotions_type"
        ),
        # Each type carries its own columns and none of the others'. Without
        # these a row can be saved that no pricing rule knows how to apply.
        CheckConstraint(
            "type <> 'percentage' OR ("
            "discount_percent IS NOT NULL AND discount_percent > 0 "
            "AND discount_percent <= 100 AND discount_amount IS NULL "
            "AND buy_quantity IS NULL AND get_quantity IS NULL)",
            name="ck_promotions_percentage_shape",
        ),
        CheckConstraint(
            "type <> 'fixed' OR ("
            "discount_amount IS NOT NULL AND discount_amount > 0 "
            "AND discount_percent IS NULL "
            "AND buy_quantity IS NULL AND get_quantity IS NULL)",
            name="ck_promotions_fixed_shape",
        ),
        CheckConstraint(
            "type <> 'bogo' OR ("
            "buy_quantity IS NOT NULL AND buy_quantity > 0 "
            "AND get_quantity IS NOT NULL AND get_quantity > 0 "
            "AND get_discount_percent IS NOT NULL AND get_discount_percent > 0 "
            "AND get_discount_percent <= 100 "
            "AND discount_percent IS NULL AND discount_amount IS NULL)",
            name="ck_promotions_bogo_shape",
        ),
        # A window that ends before it starts is never live, which is a silent
        # no-op rather than an error the operator would notice.
        CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="ck_promotions_window",
        ),
        # The pricing lookup is "active promotions whose window contains now()".
        Index(
            "ix_promotions_live",
            "is_active",
            "starts_at",
            "ends_at",
            postgresql_where=text("is_active"),
        ),
    )
