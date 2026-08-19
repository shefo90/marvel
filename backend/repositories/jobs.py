"""The job queue's data access. Everything that touches the ``jobs`` table.

``enqueue`` is the only function callers outside ``workers/`` should need, and
the important thing about it is what it does *not* do: it does not commit. The
row is added to the caller's session and flushed, so it lands in the caller's
transaction. An order and the job that captures its payment therefore commit
together or roll back together, and no window exists in which one is durable and
the other is not. That guarantee is the entire reason this queue is a table.

The rest is the worker's half of the contract. A claim is a short transaction
that marks rows ``running`` and returns plain dicts rather than ORM objects,
because the handler then runs on a different session and a detached instance
would only invite a lazy load against a closed one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import JOB_MAX_ATTEMPTS
from core.enums import JobStatus
from models.jobs import Job


# Every timestamp in this table comes from the database clock, never Python's.
# The rows are written by the API and read by the worker, which in a real
# deployment are different hosts: a job scheduled against one machine's clock
# and claimed against another's is early or late by whatever those two disagree
# by, and NTP skew of a few seconds is enough to make a retry fire immediately.
# One clock, and it is the one both processes are already talking to.
def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    *,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> Job | None:
    """Queue a job inside the caller's transaction.

    Returns the row, or ``None`` when ``dedupe_key`` matches work that is
    already outstanding. The collision is resolved by the partial unique index
    rather than by looking first: a SELECT-then-INSERT is a race, and two
    workers scheduling the next sweep at the same moment is the expected case,
    not the unlucky one. The insert runs inside a SAVEPOINT so that losing the
    race costs the caller's transaction nothing.
    """
    job = Job(
        kind=kind,
        payload=payload or {},
        status=JobStatus.pending,
        run_after=run_after if run_after is not None else func.now(),
        max_attempts=max_attempts or JOB_MAX_ATTEMPTS,
        dedupe_key=dedupe_key,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        if "uq_jobs_dedupe_key" in str(getattr(exc, "orig", exc)):
            return None
        raise
    return job


def claim(db: Session, worker_id: str, limit: int) -> list[dict]:
    """Take up to ``limit`` due jobs for this worker, as plain dicts.

    ``FOR UPDATE SKIP LOCKED`` is what makes more than one worker safe: a row
    another worker is already claiming is stepped over rather than waited on, so
    workers never serialise behind each other.

    The caller must commit promptly. The lease -- ``locked_at`` plus
    JOB_LEASE_SECONDS -- is what protects a claimed job from being lost to a
    worker that dies, and it does not start until this transaction lands.
    """
    due = (
        select(Job.id)
        .where(Job.status == JobStatus.pending, Job.run_after <= func.now())
        .order_by(Job.run_after)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    ids = list(db.execute(due).scalars())
    if not ids:
        return []

    rows = db.execute(
        update(Job)
        .where(Job.id.in_(ids))
        .values(
            status=JobStatus.running,
            locked_at=func.now(),
            locked_by=worker_id[:64],
        )
        .returning(Job.id, Job.kind, Job.payload, Job.attempts, Job.max_attempts)
        # The session's view of these rows is deliberately left stale: the
        # caller commits immediately (which expires it anyway), and the worker
        # reads the dicts below rather than the ORM objects. Anything else pays
        # for a synchronisation nobody uses.
        .execution_options(synchronize_session=False)
    ).all()
    return [
        {"id": r.id, "kind": r.kind, "payload": r.payload or {},
         "attempts": r.attempts, "max_attempts": r.max_attempts}
        for r in rows
    ]


def settle_success(db: Session, job_id: int) -> None:
    """A job that succeeded leaves no row. See models/jobs.py for why."""
    db.execute(delete(Job).where(Job.id == job_id))


def settle_failure(
    db: Session, job_id: int, error: str, delay_seconds: float
) -> str | None:
    """Charge an attempt, then reschedule or dead-letter.

    Returns the resulting status, or ``None`` if the row is gone -- which is not
    an error: a lease can expire while the handler is still running, letting the
    reaper move the row before this call arrives.
    """
    # populate_existing, because this row was very likely claimed earlier on
    # some session and the identity map may still show it pending. Writing
    # against a stale copy emits an UPDATE that omits `status`, which clears
    # locked_at while leaving status='running' -- and ck_jobs_locked_consistency
    # rejects exactly that.
    job = db.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        return None

    job.attempts += 1
    job.locked_at = None
    job.locked_by = None
    job.last_error = error
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.dead
    else:
        job.status = JobStatus.pending
        job.run_after = func.now() + timedelta(seconds=delay_seconds)
    db.flush()
    return job.status.value if hasattr(job.status, "value") else job.status


def reap_stalled(db: Session, lease_seconds: int) -> int:
    """Reclaim jobs whose worker died mid-flight. Returns how many.

    An expired lease is charged an attempt, deliberately. A handler that
    reliably kills its worker -- an unbounded allocation, a hard segfault in an
    image library -- would otherwise be reclaimed and retried forever, taking
    down each worker that touched it. Charging the attempt means it dead-letters
    like any other failure and stops.
    """
    stalled = list(
        db.execute(
            select(Job)
            .where(
                Job.status == JobStatus.running,
                Job.locked_at < func.now() - timedelta(seconds=lease_seconds),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalars()
    )
    for job in stalled:
        job.attempts += 1
        job.locked_at = None
        job.locked_by = None
        job.last_error = f"lease expired after {lease_seconds}s"
        job.status = (
            JobStatus.dead if job.attempts >= job.max_attempts else JobStatus.pending
        )
    if stalled:
        db.flush()
    return len(stalled)


def dead_letters(db: Session, limit: int = 100) -> list[Job]:
    """Everything that gave up. Section 13's dead-letter path, as a query."""
    return list(
        db.execute(
            select(Job)
            .where(Job.status == JobStatus.dead)
            .order_by(Job.created_at.desc())
            .limit(limit)
        ).scalars()
    )
