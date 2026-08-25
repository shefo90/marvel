"""The job queue's guarantees, at the repository level.

All of these run on the rolled-back ``db`` fixture, so the suite leaves no job
rows behind. Kinds carry a uuid suffix because the development database is
shared and a leftover row from an earlier run must not be able to satisfy an
assertion here.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from core.db import SessionLocal
from core.enums import JobStatus
from models.jobs import Job
from repositories.jobs import (
    claim,
    dead_letters,
    enqueue,
    reap_stalled,
    settle_failure,
    settle_success,
)
from workers.backoff import delay_seconds

CENTRE = 0.5  # the middle of the jitter window, so a delay lands on its raw value


def _kind() -> str:
    return f"test.{uuid.uuid4().hex[:12]}"


def _status(job) -> str:
    return job.status.value if hasattr(job.status, "value") else job.status


# --- the outbox property -------------------------------------------------

def test_a_job_queued_by_a_transaction_that_rolls_back_never_existed(db):
    """The whole reason this queue is a table and not a Redis list.

    A job and the change that caused it are one transaction. Nothing else can
    give that: an enqueue to a second system either happens before the commit,
    and survives a rollback that should have killed it, or after, and is lost if
    the process dies in between.
    """
    kind = _kind()
    enqueue(db, kind, {"order_id": 1})
    db.rollback()

    probe = SessionLocal()
    try:
        surviving = probe.execute(
            select(func.count()).select_from(Job).where(Job.kind == kind)
        ).scalar_one()
    finally:
        probe.close()
    assert surviving == 0


def test_a_job_is_visible_to_its_own_transaction_before_the_commit(db):
    kind = _kind()
    job = enqueue(db, kind, {"order_id": 1})

    assert job.id is not None
    assert db.execute(select(Job).where(Job.kind == kind)).scalar_one().id == job.id


# --- deduplication -------------------------------------------------------

def test_a_dedupe_key_collapses_duplicate_outstanding_work(db):
    kind = _kind()
    first = enqueue(db, kind, dedupe_key=kind)
    second = enqueue(db, kind, dedupe_key=kind)

    assert first is not None
    assert second is None, "a second row was queued for work already outstanding"


def test_losing_the_dedupe_race_leaves_the_callers_transaction_usable(db):
    """The insert runs in a SAVEPOINT precisely so this holds. Otherwise the
    loser of a routine race would take the whole caller transaction down."""
    kind = _kind()
    enqueue(db, kind, dedupe_key=kind)
    assert enqueue(db, kind, dedupe_key=kind) is None

    other = enqueue(db, _kind())
    assert other is not None and other.id is not None


def test_a_dead_row_does_not_block_the_next_occurrence(db):
    """The unique index is partial for this reason. If a dead row kept its key
    reserved, one bad night would stop a recurring sweep forever."""
    kind = _kind()
    job = enqueue(db, kind, dedupe_key=kind, max_attempts=1)
    settle_failure(db, job.id, "boom", 10)
    assert _status(db.get(Job, job.id)) == JobStatus.dead.value

    assert enqueue(db, kind, dedupe_key=kind) is not None


# --- claiming ------------------------------------------------------------

def test_claim_takes_a_due_job_and_records_the_worker(db):
    job = enqueue(db, _kind())

    claimed = claim(db, "worker-a", 100)

    assert job.id in [c["id"] for c in claimed]
    db.expire_all()  # claim does not synchronise the session; see its docstring
    row = db.get(Job, job.id)
    assert _status(row) == JobStatus.running.value
    assert row.locked_by == "worker-a"
    assert row.locked_at is not None


def test_claim_leaves_a_job_that_is_not_due_yet(db):
    job = enqueue(db, _kind(), run_after=func.now() + timedelta(hours=1))

    claimed = claim(db, "worker-a", 100)

    assert job.id not in [c["id"] for c in claimed]
    db.expire_all()
    assert _status(db.get(Job, job.id)) == JobStatus.pending.value


def test_claim_carries_the_payload_through(db):
    job = enqueue(db, _kind(), {"order_id": 42, "note": "first"})

    mine = [c for c in claim(db, "worker-a", 100) if c["id"] == job.id]

    assert mine[0]["payload"] == {"order_id": 42, "note": "first"}


# --- settling ------------------------------------------------------------

def test_success_leaves_no_row(db):
    job_id = enqueue(db, _kind()).id

    settle_success(db, job_id)

    assert db.get(Job, job_id) is None


def test_a_failure_charges_an_attempt_and_reschedules(db):
    job = enqueue(db, _kind(), max_attempts=3)

    settle_failure(db, job.id, "ConnectionError: gateway down", 60)

    db.expire_all()
    row = db.get(Job, job.id)
    assert _status(row) == JobStatus.pending.value
    assert row.attempts == 1
    assert row.last_error == "ConnectionError: gateway down"
    assert row.locked_at is None and row.locked_by is None
    assert row.run_after > db.execute(select(func.now())).scalar_one()


def test_exhausting_the_attempts_dead_letters_with_the_error(db):
    job = enqueue(db, _kind(), max_attempts=2)

    settle_failure(db, job.id, "first", 1)
    settle_failure(db, job.id, "second and last", 1)

    row = db.get(Job, job.id)
    assert _status(row) == JobStatus.dead.value
    assert row.attempts == 2
    assert row.last_error == "second and last"
    assert row.id in [d.id for d in dead_letters(db)]


def test_settling_a_job_that_is_already_gone_is_not_an_error(db):
    """A lease can expire while the handler is still running, so the reaper may
    have moved the row before the settle arrives."""
    job_id = enqueue(db, _kind()).id
    settle_success(db, job_id)

    assert settle_failure(db, job_id, "late", 10) is None


# --- the lease -----------------------------------------------------------

def test_an_expired_lease_returns_the_job_and_charges_an_attempt(db):
    """Charging the attempt is the point. A handler that kills its worker would
    otherwise be reclaimed and retried forever, taking down each worker in turn."""
    job = enqueue(db, _kind(), max_attempts=3)
    claim(db, "worker-that-died", 100)
    db.execute(
        Job.__table__.update()
        .where(Job.id == job.id)
        .values(locked_at=func.now() - timedelta(seconds=600))
    )

    reclaimed = reap_stalled(db, lease_seconds=300)

    db.expire_all()
    row = db.get(Job, job.id)
    assert reclaimed >= 1
    assert _status(row) == JobStatus.pending.value
    assert row.attempts == 1
    assert "lease expired" in row.last_error


def test_a_live_lease_is_left_alone(db):
    job = enqueue(db, _kind())
    claim(db, "worker-a", 100)

    reap_stalled(db, lease_seconds=300)

    db.expire_all()
    assert _status(db.get(Job, job.id)) == JobStatus.running.value


# --- backoff -------------------------------------------------------------

def test_backoff_doubles_each_attempt():
    assert delay_seconds(1, base=10, cap=900, rand=lambda: CENTRE) == 10
    assert delay_seconds(2, base=10, cap=900, rand=lambda: CENTRE) == 20
    assert delay_seconds(3, base=10, cap=900, rand=lambda: CENTRE) == 40


def test_backoff_is_capped():
    assert delay_seconds(20, base=10, cap=900, rand=lambda: CENTRE) == 900


def test_backoff_spreads_the_retry_across_a_window():
    """Without jitter every job that failed against the same outage comes back
    at the same instant, and keeps doing it."""
    low = delay_seconds(3, base=10, cap=900, rand=lambda: 0.0)
    high = delay_seconds(3, base=10, cap=900, rand=lambda: 1.0)

    assert low == pytest.approx(32)
    assert high == pytest.approx(48)


def test_backoff_rejects_a_zero_attempt():
    with pytest.raises(ValueError):
        delay_seconds(0)
