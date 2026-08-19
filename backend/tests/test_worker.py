"""The worker's tick, end to end against the real database.

Unlike the rest of the suite these commit, because a worker's whole job is to
act on rows another transaction committed -- a rolled-back session cannot show
that. The ``jobs_cleanup`` fixture removes every row the tick touches, including
the recurring occurrences ``ensure_recurring`` schedules, so the suite stays
repeatable.

There is no sleeping and no thread here: ``main`` is a loop around ``run_once``,
and ``run_once`` is what these drive.
"""

import uuid

import pytest
from sqlalchemy import delete, or_, select

from core.db import SessionLocal
from core.enums import JobStatus
from models.jobs import Job
from repositories.jobs import enqueue
from tasks.registry import _HANDLERS
from tasks.schedule import RECURRING
from workers.runner import run_once

ran: list[dict] = []


@pytest.fixture(autouse=True)
def jobs_cleanup():
    """Remove this module's rows, and the recurring ones every tick schedules."""
    ran.clear()
    yield
    db = SessionLocal()
    try:
        db.execute(
            delete(Job).where(
                or_(Job.kind.like("test.%"), Job.kind.in_(list(RECURRING)))
            )
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def handler(monkeypatch):
    """Register a throwaway handler and hand back its kind."""

    def _make(fn) -> str:
        kind = f"test.{uuid.uuid4().hex[:12]}"
        monkeypatch.setitem(_HANDLERS, kind, fn)
        return kind

    return _make


def _queue(kind: str, **kwargs) -> int:
    db = SessionLocal()
    try:
        job = enqueue(db, kind, **kwargs)
        db.commit()
        return job.id
    finally:
        db.close()


def _load(job_id: int) -> Job | None:
    db = SessionLocal()
    try:
        return db.get(Job, job_id)
    finally:
        db.close()


def _status(job: Job) -> str:
    return job.status.value if hasattr(job.status, "value") else job.status


def test_a_tick_runs_a_queued_job_and_leaves_no_row(handler):
    kind = handler(lambda db, payload: ran.append(payload))
    job_id = _queue(kind, payload={"order_id": 7})

    run_once("test-worker")

    assert ran == [{"order_id": 7}]
    assert _load(job_id) is None, "a job that succeeded should leave no row"


def test_a_handlers_writes_are_committed(handler):
    """The worker owns the session and commits when the handler returns, so a
    handler that only flushes still lands. A sweep that silently rolled back
    would look identical to one that had nothing to do."""
    marker = f"worker-commit-{uuid.uuid4().hex[:8]}"

    def write(db, payload):
        enqueue(db, "test.written-by-handler", {"marker": marker})

    _queue(handler(write))
    run_once("test-worker")

    db = SessionLocal()
    try:
        written = db.execute(
            select(Job).where(Job.kind == "test.written-by-handler")
        ).scalars().all()
        assert [j.payload["marker"] for j in written] == [marker]
    finally:
        db.close()


def test_a_failing_handler_is_rescheduled_rather_than_lost(handler):
    def boom(db, payload):
        raise RuntimeError("gateway timed out")

    job_id = _queue(handler(boom), max_attempts=3)

    run_once("test-worker")

    job = _load(job_id)
    assert _status(job) == JobStatus.pending.value
    assert job.attempts == 1
    assert "gateway timed out" in job.last_error
    assert job.locked_at is None


def test_a_handler_that_keeps_failing_dead_letters(handler):
    def boom(db, payload):
        raise RuntimeError("still down")

    job_id = _queue(handler(boom), max_attempts=1)

    run_once("test-worker")

    assert _status(_load(job_id)) == JobStatus.dead.value


def test_an_unknown_kind_fails_the_job_rather_than_the_worker():
    """What a rolled-back deploy looks like from the worker's side: the row must
    survive to be retried once the code that understands it is back."""
    job_id = _queue("test.nobody-handles-this", max_attempts=3)

    ticked = run_once("test-worker")

    assert ticked == 1, "the worker skipped the job instead of failing it"
    job = _load(job_id)
    assert _status(job) == JobStatus.pending.value
    assert "UnknownJobKind" in job.last_error


def test_a_handlers_failure_does_not_stop_the_rest_of_the_batch(handler):
    def boom(db, payload):
        raise RuntimeError("one bad job")

    _queue(handler(boom))
    good = handler(lambda db, payload: ran.append("good"))
    _queue(good)

    run_once("test-worker")

    assert "good" in ran


def test_recurring_work_is_scheduled_once_however_many_ticks_run():
    """Several workers all try to schedule the next occurrence; the partial
    unique index is what makes exactly one of them win."""
    run_once("test-worker-a")
    run_once("test-worker-b")

    db = SessionLocal()
    try:
        for kind in RECURRING:
            outstanding = db.execute(
                select(Job).where(
                    Job.kind == kind,
                    Job.status.in_([JobStatus.pending, JobStatus.running]),
                )
            ).scalars().all()
            assert len(outstanding) == 1, f"{kind} was scheduled {len(outstanding)} times"
    finally:
        db.close()


def test_recurring_work_is_not_due_the_moment_it_is_scheduled():
    """It is scheduled for now + interval, so a tick must not immediately claim
    and run it -- that would turn a 15-minute sweep into a hot loop."""
    run_once("test-worker")

    db = SessionLocal()
    try:
        for kind in RECURRING:
            job = db.execute(select(Job).where(Job.kind == kind)).scalars().one()
            assert _status(job) == JobStatus.pending.value
            assert job.attempts == 0
    finally:
        db.close()
