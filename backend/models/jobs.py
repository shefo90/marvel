"""The background job queue — a Postgres table, not a Redis list.

The queue is a table because a job must not be able to exist without the change
that caused it, nor the change without the job. ``repositories.jobs.enqueue``
writes the row on the *caller's* session, so an order and its "capture the
payment" job commit together or not at all. A Redis queue cannot offer that: the
enqueue is a second write to a second system, and everything between the two is
a window where a crash loses the job silently.

Two consequences of that choice are visible in this table.

**There is no ``done`` status.** A job that succeeds is deleted. What remains is
only work that is outstanding, in flight, or dead — so the table stays small
with no retention policy, and section 13's dead-letter path is a plain
``WHERE status = 'dead'`` rather than a view over history nobody prunes. The
price is that this table answers "what is broken", never "what ran last night";
domain history belongs in the domain tables (``order_payment_events`` and
friends), not here.

**A claim is a lease, not a lock.** ``locked_at``/``locked_by`` are set in a
short transaction and the handler then runs on a *different* session, because a
handler that calls a payment gateway must not hold a database transaction open
across an HTTP round trip. The cost of a lease is that a worker which dies
mid-job leaves the row claimed; ``reap_stalled`` returns it after
``JOB_LEASE_SECONDS`` and charges it an attempt, so a job that reliably kills
its worker dead-letters instead of cycling forever.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column

from core.db import Base
from core.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Registry name, e.g. "carts.sweep_abandoned". Not an enum: handlers are
    # added by adding a module, and a migration per new job kind would make the
    # queue more expensive to extend than the work it defers.
    kind = mapped_column(String(64), nullable=False)
    payload = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    status = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=16),
        nullable=False,
        server_default=JobStatus.pending.value,
    )

    # Eligibility, not creation order: retries move this forward, and a caller
    # can schedule work for later by setting it.
    run_after = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    attempts = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts = mapped_column(Integer, nullable=False, server_default="5")

    # Set only while status = 'running'; the CHECK below ties the two together.
    locked_at = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by = mapped_column(String(64), nullable=True)

    last_error = mapped_column(Text, nullable=True)

    # Collapses duplicate work. The recurring sweeps use their own kind as the
    # key, so any number of workers can try to schedule the next occurrence and
    # exactly one row results.
    dedupe_key = mapped_column(String(200), nullable=True)

    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts_positive"),
        # The same shape as ck_carts_converted_consistency: a status and the
        # column that is only meaningful in that status cannot drift apart.
        CheckConstraint(
            "(status = 'running') = (locked_at IS NOT NULL)",
            name="ck_jobs_locked_consistency",
        ),
        # The claim query's index. Partial, because pending is the only status
        # it ever scans and dead rows would otherwise bloat it.
        Index(
            "ix_jobs_claimable",
            "run_after",
            postgresql_where=text("status = 'pending'"),
        ),
        # Uniqueness only among outstanding work: a dead row must not block the
        # next occurrence of a recurring job from ever being scheduled again.
        Index(
            "uq_jobs_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text(
                "dedupe_key IS NOT NULL AND status IN ('pending', 'running')"
            ),
        ),
        Index(
            "ix_jobs_dead",
            "created_at",
            postgresql_where=text("status = 'dead'"),
        ),
    )
