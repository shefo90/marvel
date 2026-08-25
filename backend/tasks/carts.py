"""Cart lifecycle sweeps.

Two states, two different meanings, and the difference matters to a shopper:

* **abandoned** -- idle past ``CART_ABANDONED_AFTER_HOURS``. A marker for
  analytics and, later, recovery email. The basket is *not* destroyed:
  ``repositories.cart._resolve`` reactivates an abandoned cart when its owner
  comes back with the token. Without that, this sweep would quietly empty the
  basket of every shopper who took a day to decide.
* **expired** -- past ``expires_at``, which is refreshed on every cart touch to
  30 days for a guest and 90 for a signed-in customer. This one is final.

Both are conditional UPDATEs, so both are idempotent: running twice changes
nothing the first run did not already change.

Batched, because these are the only statements in the system that can touch an
unbounded number of rows. A single UPDATE over a year of dead carts would hold
locks for as long as it took; 500 at a time keeps each transaction short.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core.config import CART_ABANDONED_AFTER_HOURS
from core.enums import CartStatus
from models.carts import Cart
from tasks.registry import task

BATCH = 500


def _sweep(db: Session, statement_for, ids_for) -> int:
    """Apply an update in bounded batches until nothing is left to do."""
    total = 0
    while True:
        ids = list(db.execute(ids_for().limit(BATCH)).scalars())
        if not ids:
            return total
        db.execute(statement_for(ids))
        total += len(ids)
        if len(ids) < BATCH:
            return total


@task("carts.sweep_abandoned")
def sweep_abandoned(db: Session, payload: dict) -> None:
    """Mark idle active carts abandoned. Recoverable, not destructive."""
    cutoff = func.now() - timedelta(hours=CART_ABANDONED_AFTER_HOURS)

    def ids_for():
        return select(Cart.id).where(
            Cart.status == CartStatus.active, Cart.last_activity_at < cutoff
        )

    def statement_for(ids):
        return (
            update(Cart)
            .where(Cart.id.in_(ids))
            .values(status=CartStatus.abandoned, abandoned_at=func.now())
        )

    _sweep(db, statement_for, ids_for)


@task("carts.sweep_expired")
def sweep_expired(db: Session, payload: dict) -> None:
    """Retire carts past their TTL. Final -- these are never reactivated.

    ``converted`` is excluded rather than merely unmatched: a converted cart
    carries ``converted_order_id``, and ck_carts_converted_consistency ties the
    two together, so moving one out of ``converted`` would violate the CHECK.
    """
    def ids_for():
        return select(Cart.id).where(
            Cart.status.in_([CartStatus.active, CartStatus.abandoned]),
            Cart.expires_at.is_not(None),
            Cart.expires_at < func.now(),
        )

    def statement_for(ids):
        return update(Cart).where(Cart.id.in_(ids)).values(status=CartStatus.expired)

    _sweep(db, statement_for, ids_for)
