"""Name -> handler. The only thing that turns a ``jobs.kind`` into code.

A handler takes the worker's session and the job's payload, and returns nothing:

    @task("carts.sweep_abandoned")
    def sweep_abandoned(db: Session, payload: dict) -> None: ...

The worker owns that session and commits when the handler returns, so a handler
must never commit for itself -- doing so would settle the job's own bookkeeping
half-way through and leave the row claimed by a transaction that no longer
exists.

**Every handler must be idempotent.** A lease can expire while a handler is
still running, and at-least-once is the only delivery guarantee a queue with
retries can offer. Conditional UPDATEs are naturally idempotent; anything that
appends a row needs its own uniqueness guard.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

Handler = Callable[[Session, dict], None]

_HANDLERS: dict[str, Handler] = {}


class UnknownJobKind(LookupError):
    """A queued kind with no handler.

    Treated as an ordinary job failure rather than a crash: it is what a rolled
    back deploy looks like from the worker's side, and the row must survive to
    be retried once the code that understands it is back.
    """


def task(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if kind in _HANDLERS:
            raise RuntimeError(f"duplicate job kind: {kind}")
        _HANDLERS[kind] = fn
        return fn

    return register


def lookup(kind: str) -> Handler:
    try:
        return _HANDLERS[kind]
    except KeyError:
        raise UnknownJobKind(kind) from None


def known() -> frozenset[str]:
    return frozenset(_HANDLERS)
