"""jobs — the background queue, as a table rather than a Redis list

Section 13 requires a background job queue with exponential retry and a
dead-letter path. This is that queue.

**Why Postgres and not Redis, when Redis is already in the stack.** A job must
not be able to exist without the change that caused it, and the change must not
be able to exist without the job. Writing the row on the caller's own session
gets that for free: an order and its "capture the payment" job commit together
or roll back together. Enqueueing to Redis is a second write to a second system,
and every instruction between the commit and the enqueue is a window in which a
crash loses the job with nothing left to show it ever existed. For a sweep that
is an annoyance; for a payment capture it is money.

**There is no ``done`` status.** A job that succeeds is deleted, so the table
holds only outstanding, in-flight and dead work. It therefore stays small with
no retention policy, and the dead-letter queue is ``WHERE status = 'dead'``
rather than a view over history nobody prunes. This table answers "what is
broken", never "what ran last night".

**uq_jobs_dedupe_key is partial on purpose.** It constrains only pending and
running rows. A dead row must not permanently block the next occurrence of a
recurring job -- otherwise one bad night silently stops the sweeps forever.

Revision ID: 0006_jobs
Revises: 0005_promotions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_jobs"
down_revision: Union[str, None] = "0005_promotions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "dead", name="jobstatus",
                    native_enum=False, length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("run_after", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts_positive"),
        sa.CheckConstraint(
            "(status = 'running') = (locked_at IS NOT NULL)",
            name="ck_jobs_locked_consistency",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_claimable", "jobs", ["run_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_jobs_dedupe_key", "jobs", ["dedupe_key"], unique=True,
        postgresql_where=sa.text(
            "dedupe_key IS NOT NULL AND status IN ('pending', 'running')"
        ),
    )
    op.create_index(
        "ix_jobs_dead", "jobs", ["created_at"],
        postgresql_where=sa.text("status = 'dead'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_dead", table_name="jobs",
                  postgresql_where=sa.text("status = 'dead'"))
    op.drop_index("uq_jobs_dedupe_key", table_name="jobs",
                  postgresql_where=sa.text(
                      "dedupe_key IS NOT NULL AND status IN ('pending', 'running')"
                  ))
    op.drop_index("ix_jobs_claimable", table_name="jobs",
                  postgresql_where=sa.text("status = 'pending'"))
    op.drop_table("jobs")
