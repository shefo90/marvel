"""The signed-in shopper's own data.

The tests that matter most here are the negative ones. There is no permission
layer above ``repositories/account.py`` -- authorisation *is* the
``customer_id`` predicate on each query -- so a missing ``WHERE`` clause does
not fail loudly, it shows one shopper another shopper's orders. Every read is
therefore tested twice: once that the owner sees their row, and once that a
second, unrelated shopper does not.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

PASSWORD = "Shopper-Pass-2026!"


@pytest.fixture(autouse=True)
def _isolate_cookies(client):
    """Empty the shared client's cookie jar around every test in this file.

    ``client`` is session-scoped, so it is one cookie jar for the entire run.
    These are the only tests that make the server set cookies, and without this
    a session established here would still be attached to requests made by
    every test that follows -- an authenticated visitor arriving in suites
    written to describe an anonymous one.
    """
    client.cookies.clear()
    yield
    client.cookies.clear()



def _register(client, email):
    r = client.post(
        "/api/en/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _token(client, email):
    r = client.post(
        "/api/en/account/session", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _cleanup(emails):
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.addresses import Address
    from models.customer_credential import CustomerCredential
    from models.customer_refresh_token import CustomerRefreshToken
    from models.customers import Customer

    db = SessionLocal()
    try:
        for email in emails:
            customer = db.execute(
                select(Customer).where(Customer.email == email)
            ).scalar_one_or_none()
            if customer is None:
                continue
            for address in db.execute(
                select(Address).where(Address.customer_id == customer.id)
            ).scalars():
                db.delete(address)
            # Core deletes in dependency order. Mixing ORM deletes with the
            # relationship cascades meant SQLAlchemy queued the same row twice
            # and warned when the second DELETE matched nothing -- noise that
            # makes a genuinely surprising warning easy to scroll past.
            db.execute(
                sa_delete(CustomerCredential).where(
                    CustomerCredential.customer_id == customer.id
                )
            )
            db.execute(
                sa_delete(CustomerRefreshToken).where(
                    CustomerRefreshToken.customer_id == customer.id
                )
            )
            db.flush()
            db.delete(customer)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def shopper(client):
    """A registered shopper and their bearer headers."""
    email = f"acct-{uuid.uuid4().hex[:10]}@example.com"
    _register(client, email)
    headers = {"Authorization": f"Bearer {_token(client, email)}"}

    yield {"email": email, "headers": headers}

    _cleanup([email])


@pytest.fixture
def other_shopper(client):
    """A second, unrelated shopper. Exists to be refused."""
    email = f"other-{uuid.uuid4().hex[:10]}@example.com"
    _register(client, email)
    headers = {"Authorization": f"Bearer {_token(client, email)}"}

    yield {"email": email, "headers": headers}

    _cleanup([email])


def _place_order(email, order_number, *, total="500.00"):
    """Commit an order owned by this shopper.

    Written straight to the table rather than driven through checkout: these
    tests are about who may read an order, and going through the cart would make
    every one of them depend on pricing, stock and idempotency behaviour that
    other suites already cover. The autouse purge fixture removes it afterwards.
    """
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.customer_credential import CustomerCredential
    from models.customer_refresh_token import CustomerRefreshToken
    from models.customers import Customer
    from models.order_items import OrderItem
    from models.orders import Order
    from models.product_variants import ProductVariant

    db = SessionLocal()
    try:
        customer = db.execute(
            select(Customer).where(Customer.email == email)
        ).scalar_one()
        # order_items.variant_id is NOT NULL and (variant_id, sku) is a
        # composite FK back to product_variants, so the line cannot be
        # fabricated -- it has to name a real variant and that variant's own
        # SKU. Any seeded one will do; this is a test about who may read the
        # order, not about what is in it.
        variant = db.execute(
            select(ProductVariant).order_by(ProductVariant.id).limit(1)
        ).scalar_one_or_none()
        assert variant is not None, "the development database has no variants seeded"
        order = Order(
            order_number=order_number, customer_id=customer.id,
            status="pending", payment_status="pending", payment_method="cod",
            locale="en", currency="EGP",
            subtotal=Decimal(total), discount=Decimal("0.00"),
            tax_total=Decimal("0.00"), shipping=Decimal("0.00"),
            total=Decimal(total), gross_order_value=Decimal(total),
            cod_amount=Decimal(total), cod_collection_status="pending",
            placed_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(
            order_id=order.id, line_number=1, variant_id=variant.id,
            sku=variant.sku, product_title="Suede Sandal",
            variant_label="38 / black", quantity=2,
            unit_price=Decimal("250.00"), line_subtotal=Decimal(total),
            line_total=Decimal(total),
        ))
        db.commit()
        return order.id
    finally:
        db.close()


# --- profile -------------------------------------------------------------

def test_the_profile_is_the_signed_in_shopper(client, shopper):
    r = client.get("/api/en/account/me", headers=shopper["headers"])

    assert r.status_code == 200, r.text
    assert r.json()["email"] == shopper["email"]


def test_the_profile_needs_a_token(client):
    r = client.get("/api/en/account/me")

    assert r.status_code in (401, 403)


# --- orders --------------------------------------------------------------

def test_the_order_list_shows_this_shoppers_orders(client, shopper):
    _place_order(shopper["email"], f"ORD-ACC-{uuid.uuid4().hex[:6].upper()}")

    r = client.get("/api/en/account/orders", headers=shopper["headers"])

    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_the_order_list_never_shows_another_shoppers_orders(client, shopper, other_shopper):
    """The authorisation test. There is no permission layer above the query."""
    _place_order(shopper["email"], f"ORD-MINE-{uuid.uuid4().hex[:6].upper()}")

    r = client.get("/api/en/account/orders", headers=other_shopper["headers"])

    assert r.status_code == 200, r.text
    assert r.json() == []


def test_an_order_row_counts_its_items(client, shopper):
    _place_order(shopper["email"], f"ORD-CNT-{uuid.uuid4().hex[:6].upper()}")

    r = client.get("/api/en/account/orders", headers=shopper["headers"])

    assert r.json()[0]["item_count"] == 2


def test_an_order_row_carries_no_margin_columns(client, shopper):
    """A shopper is shown what they paid. contribution_profit, items_cogs_total
    and the gateway fee are section 11A reporting columns on the same row, and
    the response is built from an explicit field list so they cannot leak."""
    _place_order(shopper["email"], f"ORD-MAR-{uuid.uuid4().hex[:6].upper()}")

    row = client.get("/api/en/account/orders", headers=shopper["headers"]).json()[0]

    for leaked in ("contribution_profit", "items_cogs_total", "gateway_fee",
                   "net_realized_revenue", "gross_order_value"):
        assert leaked not in row


def test_one_order_comes_back_with_its_lines(client, shopper):
    number = f"ORD-DET-{uuid.uuid4().hex[:6].upper()}"
    _place_order(shopper["email"], number)

    r = client.get(f"/api/en/account/orders/{number}", headers=shopper["headers"])

    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["product_title"] == "Suede Sandal"


def test_another_shoppers_order_is_a_404_not_a_403(client, shopper, other_shopper):
    """403 would confirm the order number exists, which is the one thing
    somebody enumerating order numbers is trying to learn."""
    number = f"ORD-PRV-{uuid.uuid4().hex[:6].upper()}"
    _place_order(shopper["email"], number)

    r = client.get(f"/api/en/account/orders/{number}", headers=other_shopper["headers"])

    assert r.status_code == 404


# --- addresses -----------------------------------------------------------

ADDRESS = {
    "recipient_name": "Nour Hassan",
    "phone": "01000000000",
    "governorate": "Cairo",
    "city": "Nasr City",
    "street_address": "12 Abbas El Akkad",
}


def test_an_address_can_be_saved_and_read_back(client, shopper):
    created = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    )

    assert created.status_code == 201, created.text
    listed = client.get("/api/en/account/addresses", headers=shopper["headers"])
    assert [a["city"] for a in listed.json()] == ["Nasr City"]


def test_the_first_address_becomes_the_default(client, shopper):
    """An address book with one entry that is not the default makes checkout ask
    a question with one possible answer."""
    created = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    )

    assert created.json()["is_default_shipping"] is True


def test_making_one_address_default_clears_the_previous_one(client, shopper):
    first = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    ).json()
    second = client.post(
        "/api/en/account/addresses", headers=shopper["headers"],
        json={**ADDRESS, "city": "Maadi"},
    ).json()

    client.patch(
        f"/api/en/account/addresses/{second['id']}",
        headers=shopper["headers"], json={"is_default_shipping": True},
    )

    listed = client.get("/api/en/account/addresses", headers=shopper["headers"]).json()
    defaults = [a["id"] for a in listed if a["is_default_shipping"]]
    assert defaults == [second["id"]], f"expected only {second['id']}, got {defaults}"
    assert first["id"] not in defaults


def test_archiving_an_address_takes_it_out_of_the_book(client, shopper):
    created = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    ).json()

    removed = client.delete(
        f"/api/en/account/addresses/{created['id']}", headers=shopper["headers"]
    )

    assert removed.status_code == 204, removed.text
    listed = client.get("/api/en/account/addresses", headers=shopper["headers"]).json()
    assert listed == []


def test_archiving_the_default_promotes_another(client, shopper):
    """Otherwise the shopper has addresses and no default, and checkout
    preselects nothing -- which reads as the book having lost them."""
    first = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    ).json()
    client.post(
        "/api/en/account/addresses", headers=shopper["headers"],
        json={**ADDRESS, "city": "Maadi"},
    )

    client.delete(
        f"/api/en/account/addresses/{first['id']}", headers=shopper["headers"]
    )

    listed = client.get("/api/en/account/addresses", headers=shopper["headers"]).json()
    assert len(listed) == 1
    assert listed[0]["is_default_shipping"] is True


def test_another_shoppers_address_cannot_be_edited(client, shopper, other_shopper):
    mine = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    ).json()

    r = client.patch(
        f"/api/en/account/addresses/{mine['id']}",
        headers=other_shopper["headers"], json={"city": "Alexandria"},
    )

    assert r.status_code == 404


def test_another_shoppers_address_cannot_be_archived(client, shopper, other_shopper):
    mine = client.post(
        "/api/en/account/addresses", headers=shopper["headers"], json=ADDRESS
    ).json()

    r = client.delete(
        f"/api/en/account/addresses/{mine['id']}", headers=other_shopper["headers"]
    )

    assert r.status_code == 404
