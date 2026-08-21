"""Maintenance operations that no request path may reach.

Nothing in the shop deletes an order, and nothing should -- an order is the
record of something that happened to a shopper's money, and the schema is built
so that history accretes rather than disappears. This module exists for the one
place where that dignity does not apply: the development database, which
``test_cart_and_orders.py`` fills with real orders placed over HTTP and never
cleans up.

Deliberately **not** a repository the routes import. There is no admin endpoint
behind this and there must not be one; an operator who can delete an order can
erase evidence of a refund. It is imported by the test suite's purge fixture and
by ``scripts/purge_orders.py``, and nowhere else.

**Why deleting an order needs code at all.** Every child of ``orders`` is
``ON DELETE CASCADE`` except two: ``idempotency_keys.order_id`` and
``carts.converted_order_id``, both ``SET NULL``. The idempotency key is fine
nulled. The cart is not, because of::

    ck_carts_converted_consistency: (status = 'converted') = (converted_order_id IS NOT NULL)

A biconditional. ``SET NULL`` satisfies the right side and falsifies the left in
the same breath, so Postgres refuses the delete. Loosening the constraint was
the tempting fix and the wrong one -- it is the only thing preventing a cart
that claims to have converted into an order that does not exist. Releasing the
cart explicitly, both columns in one UPDATE, keeps the invariant true at every
instant.

A released cart becomes ``abandoned`` rather than ``active``. It had items and
the shopper is long gone; calling it active would put a stale basket back into
the abandoned-cart sweep's population as a live one.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from models.carts import Cart
from models.orders import Order


def delete_orders(db: Session, order_ids: Iterable[int]) -> int:
    """Delete these orders and release any cart pointing at them.

    Returns the number actually deleted. Ids that do not exist are skipped
    rather than raised on: the purge fixture runs after every test, including
    tests that already cleaned up after themselves.

    Does not commit. The caller owns the transaction, as everywhere else here.
    """
    ids = [int(i) for i in order_ids]
    if not ids:
        return 0

    # Both columns together. Splitting this into two statements would leave the
    # row violating ck_carts_converted_consistency between them -- which, the
    # constraint being IMMEDIATE, is not a window that exists to be used.
    db.execute(
        update(Cart)
        .where(Cart.converted_order_id.in_(ids))
        .values(status="abandoned", converted_order_id=None)
    )

    # A Core delete, so the cascade is the database's to run rather than
    # SQLAlchemy's to simulate one collection at a time.
    result = db.execute(delete(Order).where(Order.id.in_(ids)))
    db.flush()
    return result.rowcount
