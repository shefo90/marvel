"""The worker process. ``python -m workers.runner``.

One tick, in order:

1. **Schedule** any recurring job that has no outstanding row.
2. **Reap** leases whose worker died, returning those jobs to the queue.
3. **Claim** a batch, in one short transaction.
4. **Run** each claimed job on its own session, and settle it.

Steps 3 and 4 are separate transactions on purpose. The claim must commit
immediately so the lease starts and other workers step over the row; the handler
must not run inside it, because the first real user of this queue is a payment
capture and holding a database transaction open across a third-party HTTP call
is how a slow gateway becomes a database outage.

Settling is best-effort by design. If the process dies between the handler
succeeding and the row being deleted, the lease expires and the job runs again
-- which is why every handler must be idempotent (see tasks/registry.py).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import timedelta

from sqlalchemy import func

import tasks  # noqa: F401  (registers every handler)
from core.config import (
    JOB_BATCH_SIZE,
    JOB_LEASE_SECONDS,
    JOB_POLL_SECONDS,
)
from core.db import SessionLocal
from repositories.jobs import claim, enqueue, reap_stalled, settle_failure, settle_success
from tasks.registry import lookup
from tasks.schedule import RECURRING
from workers.backoff import delay_seconds

log = logging.getLogger("worker")


def worker_id() -> str:
    """Host and pid — enough to tell two workers apart in ``jobs.locked_by``."""
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


def ensure_recurring(db) -> None:
    """Queue the next occurrence of anything recurring that has none.

    Losing the race is the normal outcome with several workers running, so a
    ``None`` from enqueue is not worth logging.
    """
    for kind, interval in RECURRING.items():
        enqueue(db, kind, run_after=func.now() + interval, dedupe_key=kind)


def run_job(job: dict) -> None:
    """Run one claimed job on a fresh session and settle it.

    Never raises: a handler that fails is bookkeeping, not a reason to take the
    worker down with it.
    """
    db = SessionLocal()
    try:
        lookup(job["kind"])(db, job["payload"])
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a failed job must not stop the worker
        db.rollback()
        log.warning("job %s (%s) failed: %s", job["id"], job["kind"], exc)
        _settle(job, error=f"{type(exc).__name__}: {exc}")
        return
    finally:
        db.close()

    _settle(job, error=None)


def _settle(job: dict, error: str | None) -> None:
    """Record the outcome in its own session, so it cannot be rolled back with
    the handler's work."""
    db = SessionLocal()
    try:
        if error is None:
            settle_success(db, job["id"])
        else:
            settle_failure(
                db, job["id"], error, delay_seconds(job["attempts"] + 1)
            )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("job %s could not be settled; its lease will expire", job["id"])
    finally:
        db.close()


def run_once(worker: str | None = None) -> int:
    """One full tick. Returns how many jobs ran. This is the unit tests drive."""
    worker = worker or worker_id()

    db = SessionLocal()
    try:
        ensure_recurring(db)
        reaped = reap_stalled(db, JOB_LEASE_SECONDS)
        if reaped:
            log.warning("reclaimed %d job(s) from an expired lease", reaped)
        batch = claim(db, worker, JOB_BATCH_SIZE)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("could not claim work")
        return 0
    finally:
        db.close()

    for job in batch:
        run_job(job)
    return len(batch)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stopping = False

    def stop(signum, _frame) -> None:
        nonlocal stopping
        # Finish the batch in hand rather than abandoning claimed jobs to their
        # lease -- a clean shutdown should not cost JOB_LEASE_SECONDS of delay.
        log.info("signal %s received; finishing the current batch", signum)
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    worker = worker_id()
    log.info("worker %s started; polling every %ss", worker, JOB_POLL_SECONDS)
    while not stopping:
        ran = run_once(worker)
        if not ran and not stopping:
            time.sleep(JOB_POLL_SECONDS)
    log.info("worker %s stopped", worker)


if __name__ == "__main__":
    main()
