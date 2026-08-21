"""Deleting orders, which the schema deliberately makes awkward.

Nothing in the shop deletes an order, and nothing should: an order is the record
of a thing that happened to somebody's money. But the development database has
no such dignity -- ``test_cart_and_orders.py`` places real orders over HTTP and
they accumulate forever -- and cleaning them up ran straight into a constraint.

``ck_carts_converted_consistency`` is a biconditional:
``(status = 'converted') = (converted_order_id IS NOT NULL)``. Deleting an order
fires the cart FK's ``ON DELETE SET NULL``, which satisfies the right-hand side
and breaks the left, so the delete is refused. Every other child of ``orders``
cascades cleanly; the cart is the only thing standing in the way.

The constraint is right and stays. What was missing is a caller that releases
the cart *first* -- moving status off ``converted`` and nulling the id in one
statement, so the row is never momentarily inconsistent.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from models.carts import Cart
from models.customers import Customer
from models.orders import Order
from repositories.maintenance import delete_orders


def _customer(db) -> Customer:
    existing = (
        db.query(Customer).filter(Customer.email == "purge-shopper@example.com").first()
    )
    if existing is not None:
        return existing
    customer = Customer(email="purge-shopper@example.com", status="active")
    db.add(customer)
    db.flush()
    return customer


def _order(db, number: str) -> Order:
    order = Order(
        order_number=number, customer_id=_customer(db).id,
        status="pending", payment_status="pending", payment_method="cod",
        locale="en", currency="EGP",
        subtotal=Decimal("500.00"), discount=Decimal("0.00"),
        tax_total=Decimal("0.00"), shipping=Decimal("0.00"),
        total=Decimal("500.00"), gross_order_value=Decimal("500.00"),
        cod_amount=Decimal("500.00"), cod_collection_status="pending",
        placed_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.flush()
    return order


def _converted_cart(db, order: Order, token: str) -> Cart:
    cart = Cart(
        token=token, customer_id=order.customer_id, status="converted",
        locale="en", currency="EGP", converted_order_id=order.id,
        converted_at=datetime.now(timezone.utc),
    )
    db.add(cart)
    db.flush()
    return cart


def test_a_bare_delete_of_a_converted_order_is_refused(db):
    """Documents why delete_orders has to exist at all."""
    order = _order(db, "ORD-PURGE-BARE")
    _converted_cart(db, order, "purge-token-bare")

    db.delete(order)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_delete_orders_removes_an_order_whose_cart_converted(db):
    order = _order(db, "ORD-PURGE-1")
    _converted_cart(db, order, "purge-token-1")
    order_id = order.id

    delete_orders(db, [order_id])

    assert db.get(Order, order_id) is None


def test_delete_orders_keeps_the_cart_and_releases_it(db):
    """The cart is a shopper's browsing history, not the order's property."""
    order = _order(db, "ORD-PURGE-2")
    cart = _converted_cart(db, order, "purge-token-2")
    cart_id = order_id = None
    cart_id, order_id = cart.id, order.id

    delete_orders(db, [order_id])

    released = db.get(Cart, cart_id)
    assert released is not None, "deleting an order must not delete the cart"
    assert released.converted_order_id is None
    assert released.status != "converted"


def test_delete_orders_takes_its_children_with_it(db):
    """The children are ON DELETE CASCADE. This pins that they stay that way.

    ``order_status_history`` stands in for the dozen tables that cascade off an
    order: it is the one with the fewest required columns, so the test says
    something about the cascade rather than about order-item construction.
    """
    from models.order_status_history import OrderStatusHistory

    order = _order(db, "ORD-PURGE-3")
    order_id = order.id
    db.add(OrderStatusHistory(
        order_id=order_id, dimension="order", to_status="pending",
        actor_type="system",
    ))
    db.flush()

    delete_orders(db, [order_id])

    remaining = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .count()
    )
    assert remaining == 0


def test_delete_orders_ignores_an_id_that_is_already_gone(db):
    """The purge fixture runs after every test, including ones that deleted
    their own orders. A missing id is not an error."""
    delete_orders(db, [999_999_999])


def test_delete_orders_reports_how_many_it_removed(db):
    order = _order(db, "ORD-PURGE-4")

    assert delete_orders(db, [order.id, 999_999_999]) == 1
