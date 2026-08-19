"""Order management for the back-office.

The storefront places orders; until now nothing could see them. This is the
`operations` half of the role ladder, which has been reserved since S1 and
unused.

Two rules shape it:

* **Status changes are recorded, not merely applied.** ``order_status_history``
  exists so the question "who moved this to shipped, and when" has an answer —
  a status column alone answers only "what is it now".
* **A status change is not a money change.** Nothing here touches ``total``,
  ``subtotal`` or ``discount``: those are audited by a database trigger and
  belong to refunds, which are S4's.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.customers import Customer
from models.order_status_history import OrderStatusHistory
from models.orders import Order
from models.users import User
from repositories.admin_orders import (
    get_order_for_admin,
    list_orders_for_admin,
    update_order_status,
)


def _actor(db, role: str = "operations") -> User:
    email = f"order-{role}@example.com"
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        return existing
    user = User(
        email=email, password_hash="x", full_name="Ops", role=role, is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _customer(db) -> Customer:
    existing = db.query(Customer).filter(Customer.email == "order-shopper@example.com").first()
    if existing is not None:
        return existing
    customer = Customer(email="order-shopper@example.com", status="active")
    db.add(customer)
    db.flush()
    return customer


def _order(db, number: str, **overrides) -> Order:
    values = {
        "status": "pending",
        "payment_status": "pending",
        "payment_method": "cod",
        "locale": "en",
        "currency": "EGP",
        "subtotal": Decimal("500.00"),
        "discount": Decimal("0.00"),
        "tax_total": Decimal("0.00"),
        "shipping": Decimal("0.00"),
        "total": Decimal("500.00"),
        "gross_order_value": Decimal("500.00"),
        "cod_amount": Decimal("500.00"),
        "cod_collection_status": "pending",
        "placed_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    order = Order(order_number=number, customer_id=_customer(db).id, **values)
    db.add(order)
    db.flush()
    return order


def test_the_listing_returns_orders_newest_first(db):
    """An operator opens this screen to see what just came in."""
    _order(db, "ORD-T-1")
    _order(db, "ORD-T-2")

    rows = list_orders_for_admin(db)["items"]

    numbers = [row["order_number"] for row in rows]
    assert numbers.index("ORD-T-2") < numbers.index("ORD-T-1")


def test_the_listing_can_be_filtered_by_status(db):
    _order(db, "ORD-T-PENDING", status="pending")
    _order(db, "ORD-T-SHIPPED", status="shipped")

    rows = list_orders_for_admin(db, status="shipped")["items"]

    assert all(row["status"] == "shipped" for row in rows)
    assert "ORD-T-SHIPPED" in {row["order_number"] for row in rows}


def test_the_listing_finds_an_order_by_its_number(db):
    """The number is what a shopper quotes on the phone, so it is the search."""
    _order(db, "ORD-T-FINDME")

    rows = list_orders_for_admin(db, search="FINDME")["items"]

    assert [row["order_number"] for row in rows] == ["ORD-T-FINDME"]


def test_an_unknown_status_filter_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        list_orders_for_admin(db, status="teleported")

    assert exc.value.status_code == 422


def test_the_detail_carries_the_money_and_the_history(db):
    order = _order(db, "ORD-T-DETAIL")

    detail = get_order_for_admin(db, "ORD-T-DETAIL")

    assert detail["total"] == "500.00"
    assert detail["items"] == []
    assert detail["status_history"] == []
    assert detail["order_id"] == order.id


def test_an_unknown_order_number_is_404(db):
    with pytest.raises(HTTPException) as exc:
        get_order_for_admin(db, "ORD-NOPE")

    assert exc.value.status_code == 404


def test_advancing_the_status_records_who_did_it(db):
    """order_status_history exists so "who moved this to shipped, and when" has
    an answer. A status column alone answers only "what is it now"."""
    order = _order(db, "ORD-T-ADVANCE")
    actor = _actor(db)

    update_order_status(db, actor, "ORD-T-ADVANCE", "confirmed", reason="Stock checked")

    row = db.execute(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
    ).scalar_one()
    assert (row.from_status, row.to_status) == ("pending", "confirmed")
    assert row.actor_user_id == actor.id
    assert row.actor_type == "staff"
    assert row.reason == "Stock checked"


def test_the_order_itself_moves(db):
    _order(db, "ORD-T-MOVES")

    updated = update_order_status(db, _actor(db), "ORD-T-MOVES", "confirmed")

    assert updated.status == "confirmed"


def test_a_status_outside_the_lifecycle_is_refused(db):
    _order(db, "ORD-T-BADSTATUS")

    with pytest.raises(HTTPException) as exc:
        update_order_status(db, _actor(db), "ORD-T-BADSTATUS", "teleported")

    assert exc.value.status_code == 422


def test_an_impossible_transition_is_refused(db):
    """A delivered order cannot go back to pending. Without this the history
    records a sequence that never happened in the real world, and every funnel
    built on it is wrong."""
    _order(db, "ORD-T-BACKWARDS", status="delivered")

    with pytest.raises(HTTPException) as exc:
        update_order_status(db, _actor(db), "ORD-T-BACKWARDS", "pending")

    assert exc.value.status_code == 409


def test_a_cancelled_order_is_final(db):
    _order(db, "ORD-T-CANCELLED", status="cancelled")

    with pytest.raises(HTTPException) as exc:
        update_order_status(db, _actor(db), "ORD-T-CANCELLED", "shipped")

    assert exc.value.status_code == 409


def test_moving_to_the_status_it_already_has_changes_nothing(db):
    """Two operators clicking the same button must not write two history rows
    describing a transition that did not happen."""
    order = _order(db, "ORD-T-SAME", status="confirmed")

    update_order_status(db, _actor(db), "ORD-T-SAME", "confirmed")

    rows = db.execute(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
    ).scalars().all()
    assert rows == []


def test_delivering_a_cod_order_marks_the_cash_collected(db):
    """The courier hands over the money at delivery. Leaving
    cod_collection_status at 'pending' would mean the books say nobody paid for
    an order that is in the customer's hands."""
    _order(db, "ORD-T-COD", status="shipped", cod_collection_status="pending")

    updated = update_order_status(db, _actor(db), "ORD-T-COD", "delivered")

    assert updated.cod_collection_status == "collected"


def test_a_status_change_never_touches_the_money(db):
    """Money moves through refunds, which are audited by a database trigger.
    A status screen that could edit a total would bypass that entirely."""
    order = _order(db, "ORD-T-MONEY")
    before = order.total

    update_order_status(db, _actor(db), "ORD-T-MONEY", "confirmed")

    assert order.total == before


# --- Over HTTP: the role gate is the point ----------------------------------

import uuid  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from repositories.register import create_staff_user  # noqa: E402

PASSWORD = "Adm1n-Ord-Test!"


@pytest.fixture
def staff_token(client):
    created: list[int] = []

    def _make(role: str) -> str:
        email = f"admin-test-ord-{role}-{uuid.uuid4().hex[:8]}@example.com"
        session = SessionLocal()
        try:
            user = create_staff_user(
                session, email=email, password=PASSWORD, full_name=f"Test {role}",
                role=role,
            )
            created.append(user.id)
        finally:
            session.close()
        r = client.post(
            "/api/en/auth/staff/login", json={"email": email, "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    yield _make

    session = SessionLocal()
    try:
        for uid in created:
            user = session.get(User, uid)
            if user is not None:
                session.delete(user)
        session.commit()
    finally:
        session.close()


def test_the_order_list_requires_a_token(client):
    assert client.get("/api/admin/orders").status_code == 403


def test_catalog_role_cannot_see_orders(client, staff_token):
    """The person who writes product descriptions is not automatically the
    person who can read every customer's order. The ladder reserved
    `operations` for this since S1."""
    token = staff_token("catalog")

    r = client.get("/api/admin/orders", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 403


def test_operations_role_reads_the_order_list(client, staff_token):
    token = staff_token("operations")

    r = client.get("/api/admin/orders", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert isinstance(r.json()["items"], list)


def test_an_unknown_status_filter_is_refused_over_http(client, staff_token):
    token = staff_token("operations")

    r = client.get(
        "/api/admin/orders?status=teleported",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 422, r.text
