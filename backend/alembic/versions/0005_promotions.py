"""promotions — the operator's offers, and where a line's discount came from

Section 4 of ``docs/superpowers/specs/2026-08-17-admin-back-office-design.md``.

This replaces S1b's promotions *rules engine*. There is no priority column and
no redemptions table: with best-single-discount-wins and no coupon codes, a
redemption count is a query over ``order_items``, and storing a derivable number
invites it to disagree with the orders it summarises.

Two things here are worth reading before changing them.

**The value columns are tied to ``type`` by CHECK constraints.** A percentage
promotion cannot carry a fixed amount; a BOGO cannot be saved without its
quantities. These rows price real baskets, so a half-specified promotion is not
a validation nicety — it is a wrong number on somebody's order.

**``discount_source`` exists to keep a markdown out of campaign cost.**
``orders.promotion_cost_total`` sums only the lines whose discount came from a
promotion. A ``sale_price`` markdown stays visible as
``unit_list_price - unit_price`` without being counted as spend, which is what
section 11A's auditability requirement actually asks for.

Both new ``order_items`` columns sit on a table whose money columns are watched
by the migration-0004 audit trigger. ``discount_amount`` was already watched;
these two are attribution rather than money, so the trigger is unchanged.

Revision ID: 0005_promotions
Revises: 0004_audit_integrity
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_promotions"
down_revision: Union[str, None] = "0004_audit_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("buy_quantity", sa.Integer(), nullable=True),
        sa.Column("get_quantity", sa.Integer(), nullable=True),
        sa.Column("get_discount_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('percentage', 'fixed', 'bogo')", name="ck_promotions_type"),
        sa.CheckConstraint(
            "type <> 'percentage' OR ("
            "discount_percent IS NOT NULL AND discount_percent > 0 "
            "AND discount_percent <= 100 AND discount_amount IS NULL "
            "AND buy_quantity IS NULL AND get_quantity IS NULL)",
            name="ck_promotions_percentage_shape",
        ),
        sa.CheckConstraint(
            "type <> 'fixed' OR ("
            "discount_amount IS NOT NULL AND discount_amount > 0 "
            "AND discount_percent IS NULL "
            "AND buy_quantity IS NULL AND get_quantity IS NULL)",
            name="ck_promotions_fixed_shape",
        ),
        sa.CheckConstraint(
            "type <> 'bogo' OR ("
            "buy_quantity IS NOT NULL AND buy_quantity > 0 "
            "AND get_quantity IS NOT NULL AND get_quantity > 0 "
            "AND get_discount_percent IS NOT NULL AND get_discount_percent > 0 "
            "AND get_discount_percent <= 100 "
            "AND discount_percent IS NULL AND discount_amount IS NULL)",
            name="ck_promotions_bogo_shape",
        ),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name="ck_promotions_window",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name=op.f("fk_promotions_created_by_user_id"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotions")),
    )
    op.create_index(
        "ix_promotions_live", "promotions",
        ["is_active", "starts_at", "ends_at"],
        unique=False, postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "promotion_targets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('all', 'product', 'variant', 'category', 'collection')",
            name="ck_promotion_targets_type",
        ),
        sa.CheckConstraint(
            "(target_type = 'all' AND target_id IS NULL) "
            "OR (target_type <> 'all' AND target_id IS NOT NULL)",
            name="ck_promotion_targets_id_matches_type",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"],
            name=op.f("fk_promotion_targets_promotion_id"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotion_targets")),
    )
    # NULLS NOT DISTINCT so a second ('all', NULL) row for one promotion is
    # refused -- without it the default NULL-is-distinct rule lets duplicates in.
    op.execute(
        "ALTER TABLE promotion_targets ADD CONSTRAINT uq_promotion_targets_unique "
        "UNIQUE NULLS NOT DISTINCT (promotion_id, target_type, target_id)"
    )
    op.create_index(
        "ix_promotion_targets_target", "promotion_targets",
        ["target_type", "target_id"], unique=False,
    )

    op.add_column("cart_items", sa.Column("promotion_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "cart_items",
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
    )
    op.add_column("cart_items", sa.Column("discount_source", sa.String(length=16), nullable=True))
    op.create_foreign_key(
        op.f("fk_cart_items_promotion_id"), "cart_items", "promotions",
        ["promotion_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_cart_items_discount_source", "cart_items",
        "discount_source IS NULL OR discount_source IN ('sale_price', 'promotion')",
    )
    op.create_check_constraint(
        "ck_cart_items_discount_non_negative", "cart_items", "discount_amount >= 0",
    )

    op.add_column("order_items", sa.Column("promotion_id", sa.BigInteger(), nullable=True))
    op.add_column("order_items", sa.Column("discount_source", sa.String(length=16), nullable=True))
    op.create_foreign_key(
        op.f("fk_order_items_promotion_id"), "order_items", "promotions",
        ["promotion_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_order_items_discount_source", "order_items",
        "discount_source IS NULL OR discount_source IN ('sale_price', 'promotion')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_items_discount_source", "order_items", type_="check")
    op.drop_constraint(op.f("fk_order_items_promotion_id"), "order_items", type_="foreignkey")
    op.drop_column("order_items", "discount_source")
    op.drop_column("order_items", "promotion_id")

    op.drop_constraint("ck_cart_items_discount_non_negative", "cart_items", type_="check")
    op.drop_constraint("ck_cart_items_discount_source", "cart_items", type_="check")
    op.drop_constraint(op.f("fk_cart_items_promotion_id"), "cart_items", type_="foreignkey")
    op.drop_column("cart_items", "discount_source")
    op.drop_column("cart_items", "discount_amount")
    op.drop_column("cart_items", "promotion_id")

    op.drop_index("ix_promotion_targets_target", table_name="promotion_targets")
    op.drop_table("promotion_targets")
    op.drop_index("ix_promotions_live", table_name="promotions", postgresql_where=sa.text("is_active"))
    op.drop_table("promotions")
