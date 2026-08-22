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

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from models.carts import Cart
from models.customer_merge import CustomerMerge
from models.customers import Customer
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


def delete_customers(db: Session, customer_ids: Iterable[int]) -> int:
    """Delete these customers, clearing the references that would refuse it.

    The same accumulation as ``delete_orders``, one table along.
    ``test_cart_and_orders.py`` resolves a guest customer for every checkout it
    performs, so the development database had built up 988 of them beside the
    1,115 orders.

    Customers are harder to remove than orders because most of what points at
    them cascades, but four references are ``ON DELETE RESTRICT`` and the
    database simply refuses instead:

    - ``orders.customer_id`` -- **not** handled here. A customer who has ordered
      is skipped rather than having their orders deleted underneath them:
      erasing sales history as a side effect of tidying up a customer row is not
      a decision this function gets to make. The purge fixture calls
      ``delete_orders`` first, so a customer whose orders were also created by
      the test is gone by the time this runs.
    - ``customer_merge`` twice, and ``customers.merged_into_customer_id`` -- all
      three are cleared here, because none of them is history about money. A
      merge record for a customer who no longer exists describes nothing.

    Returns how many were actually deleted, which may be fewer than were asked
    for. Skipping quietly is right for a cleanup that runs after every test;
    raising would turn a passing test red for a row it does not own.
    """
    ids = [int(i) for i in customer_ids]
    if not ids:
        return 0

    still_ordering = set(
        db.execute(
            select(Order.customer_id).where(Order.customer_id.in_(ids))
        ).scalars()
    )
    doomed = [i for i in ids if i not in still_ordering]
    if not doomed:
        return 0

    db.execute(
        delete(CustomerMerge).where(
            or_(
                CustomerMerge.surviving_customer_id.in_(doomed),
                CustomerMerge.merged_customer_id.in_(doomed),
            )
        )
    )
    # A survivor pointing at a doomed row blocks the delete, and the survivor is
    # not ours to remove. All three columns move together:
    # ``ck_customers_merge_consistency`` is a biconditional -- the pointer, the
    # timestamp and ``status = 'merged'`` are legal only as a set -- so nulling
    # the pointer alone is refused, exactly as nulling a cart's
    # converted_order_id alone is. The row becomes 'active' again because a
    # customer merged into someone who no longer exists stands on their own.
    db.execute(
        update(Customer)
        .where(Customer.merged_into_customer_id.in_(doomed))
        .values(merged_into_customer_id=None, merged_at=None, status="active")
    )
    db.flush()

    result = db.execute(delete(Customer).where(Customer.id.in_(doomed)))
    db.flush()
    return result.rowcount
