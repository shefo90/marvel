"""Cache work that must not happen until the transaction has actually committed.

Invalidating inside the write transaction looks right and is not. The route
layer owns the commit -- repositories flush, routes call ``db.commit()`` -- so
an invalidation issued from a repository lands while the new rows are still
invisible to everyone else. A storefront read arriving in that window reads the
*old* committed row, stores it under the key that was just dropped, and that
copy then outlives the commit for the rest of its TTL. For the product payload
that is ``TTL_PRICING``: sixty seconds of serving the previous price to
shoppers after the operator has been told the change saved.

Deferring closes the systematic window. It does not close the theoretical one
-- a reader that loaded the old row *before* the commit can still write it back
immediately after -- but that race is a few milliseconds wide and unavoidable
without read-through locking, which ``services.cache.get_or_set`` deliberately
declines to do. The pre-commit ordering, by contrast, left the window open for
the whole duration of the transaction on every single write.

Work is queued against the session, not a global, so two requests never see
each other's queue. The queue is dropped on rollback: a transaction that never
landed has nothing to invalidate.

Keys are built inside the queued callable, not when it is queued, so the
namespace version is read at delete time. Everything the callable needs from
the database must be captured *before* it is queued -- ``after_commit`` fires on
a session with no transaction, and emitting SQL there would silently open a new
one.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_PENDING = "cache_invalidation_pending"


def on_commit(session: Session, work: Callable[[], None]) -> None:
    """Queue ``work`` to run once, after ``session``'s transaction commits."""
    session.info.setdefault(_PENDING, []).append(work)


def run_pending(session: Session) -> None:
    """Run everything queued on this session, then clear the queue.

    Failures are logged and swallowed. By the time this runs the write is
    already durable, so raising would report a failure for work that succeeded
    -- the operator would retry a save that had in fact landed. A cache entry
    that outlives its invalidation is bounded by its TTL; a 500 on a successful
    write is not bounded by anything.
    """
    for work in session.info.pop(_PENDING, ()):
        try:
            work()
        except Exception:  # noqa: BLE001 - see docstring
            log.exception("cache: deferred invalidation failed")


def discard_pending(session: Session) -> None:
    """Forget everything queued. The transaction is not going to land."""
    session.info.pop(_PENDING, None)


# Registered on the Session class, so every session gets this without having to
# be built by a particular factory -- including the ones the test suite makes.
@event.listens_for(Session, "after_commit")
def _run_on_commit(session: Session) -> None:
    run_pending(session)


@event.listens_for(Session, "after_rollback")
def _discard_on_rollback(session: Session) -> None:
    discard_pending(session)


@event.listens_for(Session, "after_soft_rollback")
def _discard_on_soft_rollback(session: Session, previous_transaction) -> None:
    discard_pending(session)
