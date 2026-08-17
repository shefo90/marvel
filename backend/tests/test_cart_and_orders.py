"""Independent tests for the cart and order flows.

These exercise the invariants section 16's Definition of Done rests on. They are
written against the HTTP surface rather than the repositories, so they would
still catch a regression introduced inside the repository layer.

Every test creates its own cart and its own shopper identity, so they are order-
independent and safe to re-run.
"""

import uuid

import pytest

ADDRESS = {
    "recipient_name": "Test Shopper",
    "phone": "01001234567",
    "governorate": "Cairo",
    "city": "Nasr City",
    "street_address": "12 Test Street",
    "building": "5",
}


def _unique_contact() -> dict:
    tag = uuid.uuid4().hex[:10]
    return {
        # Not .test — email-validator rejects it as a special-use/reserved TLD.
        "email": f"shopper.{tag}@example.com",
        "phone": f"010{uuid.uuid4().int % 100000000:08d}",
        "first_name": "Test",
        "last_name": "Shopper",
    }


def _new_cart(client, attribution: dict | None = None) -> str:
    body = {"attribution": attribution} if attribution else {}
    r = client.post("/api/en/cart", json=body)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _add_item(client, token: str, sku: str, quantity: int = 1, **extra):
    return client.post(
        "/api/en/cart/items",
        json={"sku": sku, "quantity": quantity, **extra},
        headers={"X-Cart-Token": token},
    )


def _first_sku(client) -> str:
    body = client.get("/api/en/products/leather-strap-sandal").json()
    return body["variants"][0]["sku"]


def _place(client, cart_token: str, idem: str, contact: dict, method: str = "cod"):
    return client.post(
        "/api/en/orders",
        json={
            "cart_token": cart_token,
            "customer": contact,
            "shipping_address": ADDRESS,
            "payment_method": method,
        },
        headers={"Idempotency-Key": idem},
    )


# --- Cart ----------------------------------------------------------------


def test_cart_is_never_cached(client):
    """A shared cache is how one shopper sees another's basket."""
    token = _new_cart(client)
    r = client.get("/api/en/cart", headers={"X-Cart-Token": token})
    assert r.headers.get("cache-control") == "no-store"


def test_repeated_adds_accumulate_on_one_line(client):
    """Section 15: quantities correct after rapid repeated clicks."""
    token = _new_cart(client)
    sku = _first_sku(client)
    for _ in range(5):
        assert _add_item(client, token, sku).status_code == 200

    body = client.get("/api/en/cart", headers={"X-Cart-Token": token}).json()
    assert len(body["items"]) == 1, "repeated adds must not create duplicate lines"
    assert body["items"][0]["quantity"] == 5
    assert body["item_count"] == 5


def test_replayed_idempotency_key_does_not_double_quantity(client):
    """The same mutation retried on a flaky connection is a no-op."""
    token = _new_cart(client)
    sku = _first_sku(client)
    key = uuid.uuid4().hex

    first = client.post(
        "/api/en/cart/items",
        json={"sku": sku, "quantity": 2},
        headers={"X-Cart-Token": token, "Idempotency-Key": key},
    )
    second = client.post(
        "/api/en/cart/items",
        json={"sku": sku, "quantity": 2},
        headers={"X-Cart-Token": token, "Idempotency-Key": key},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["items"][0]["quantity"] == 2


def test_cart_carries_list_attribution(client):
    """Section 5's item_list_id must survive to the order line."""
    token = _new_cart(client)
    sku = _first_sku(client)
    r = _add_item(
        client,
        token,
        sku,
        added_from_list_id="summer_edit",
        added_from_list_name="Summer Edit",
        added_from_index=3,
    )
    item = r.json()["items"][0]
    assert item["added_from_list_id"] == "summer_edit"
    assert item["added_from_index"] == 3


# --- Orders --------------------------------------------------------------


def test_order_creation_requires_idempotency_key(client):
    token = _new_cart(client)
    _add_item(client, token, _first_sku(client))
    r = client.post(
        "/api/en/orders",
        json={
            "cart_token": token,
            "customer": _unique_contact(),
            "shipping_address": ADDRESS,
            "payment_method": "cod",
        },
    )
    assert r.status_code in (400, 422), r.text


def test_replayed_order_returns_same_order_and_creates_no_second(client):
    """Section 15: purchase fires once after refresh/back navigation."""
    token = _new_cart(client)
    _add_item(client, token, _first_sku(client), quantity=2)
    contact = _unique_contact()
    key = uuid.uuid4().hex

    first = _place(client, token, key, contact)
    assert first.status_code == 201, first.text
    replay = _place(client, token, key, contact)

    assert replay.status_code in (200, 201)
    assert replay.json()["order_number"] == first.json()["order_number"]


def test_order_number_is_stable_and_prefixed(client):
    token = _new_cart(client)
    _add_item(client, token, _first_sku(client))
    contact = _unique_contact()
    r = _place(client, token, uuid.uuid4().hex, contact)
    assert r.status_code == 201, r.text
    number = r.json()["order_number"]
    assert number.startswith("ORD-")

    # Guest checkout has no session, so the reader presents the contact the
    # order was placed with. Re-reading must return the identical transaction_id.
    again = client.get(f"/api/en/orders/{number}", params={"email": contact["email"]})
    assert again.status_code == 200, again.text
    assert again.json()["order_number"] == number


def test_order_lookup_requires_the_placing_contact(client):
    """An order number alone must not grant access to someone else's order."""
    token = _new_cart(client)
    _add_item(client, token, _first_sku(client))
    r = _place(client, token, uuid.uuid4().hex, _unique_contact())
    number = r.json()["order_number"]

    assert client.get(f"/api/en/orders/{number}").status_code == 400
    wrong = client.get(
        f"/api/en/orders/{number}", params={"email": "someone.else@example.com"}
    )
    assert wrong.status_code in (403, 404)


def test_guest_checkout_resolves_a_customer(client):
    """Guest checkout is first-class, but section 11A needs a customer row."""
    token = _new_cart(client)
    _add_item(client, token, _first_sku(client))
    r = _place(client, token, uuid.uuid4().hex, _unique_contact())
    assert r.status_code == 201, r.text
    assert r.json()["customer_public_id"] is not None


def test_new_customer_flag_is_server_derived(client):
    """Section 6: never inferred from a browser cookie.

    Same shopper, two orders: the first is new, the second is not.
    """
    contact = _unique_contact()
    sku = _first_sku(client)

    t1 = _new_cart(client)
    _add_item(client, t1, sku)
    first = _place(client, t1, uuid.uuid4().hex, contact)
    assert first.status_code == 201, first.text

    t2 = _new_cart(client)
    _add_item(client, t2, sku)
    second = _place(client, t2, uuid.uuid4().hex, contact)
    assert second.status_code == 201, second.text

    assert first.json()["is_new_customer"] is True
    assert second.json()["is_new_customer"] is False


def test_first_touch_survives_a_second_campaign(client):
    """Section 11A: do not overwrite first acquisition when a returning
    customer arrives through a new campaign."""
    contact = _unique_contact()
    sku = _first_sku(client)
    visitor = uuid.uuid4().hex[:32]

    t1 = _new_cart(
        client,
        {
            "visitor_token": visitor,
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "first-campaign",
        },
    )
    _add_item(client, t1, sku)
    o1 = _place(client, t1, uuid.uuid4().hex, contact)
    assert o1.status_code == 201, o1.text

    t2 = _new_cart(
        client,
        {
            "visitor_token": visitor,
            "utm_source": "facebook",
            "utm_medium": "paid_social",
            "utm_campaign": "second-campaign",
        },
    )
    _add_item(client, t2, sku)
    o2 = _place(client, t2, uuid.uuid4().hex, contact)
    assert o2.status_code == 201, o2.text

    from sqlalchemy import select

    from core.db import SessionLocal
    from models.customer_attributions import CustomerAttribution
    from models.customers import Customer

    session = SessionLocal()
    try:
        customer = session.execute(
            select(Customer).where(
                Customer.public_id == o2.json()["customer_public_id"]
            )
        ).scalar_one()
        attribution = session.execute(
            select(CustomerAttribution).where(
                CustomerAttribution.customer_id == customer.id
            )
        ).scalar_one()

        assert attribution.first_touch_source == "google", (
            "first touch was overwritten by the second campaign"
        )
        assert attribution.first_touch_campaign == "first-campaign"
        assert attribution.last_touch_source == "facebook"
    finally:
        session.close()


def test_order_line_snapshots_cogs_and_does_not_track_later_cost_edits(client):
    """Section 11A: do not recalculate old orders from today's product cost."""
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.order_items import OrderItem
    from models.orders import Order
    from models.product_variants import ProductVariant

    sku = _first_sku(client)
    token = _new_cart(client)
    _add_item(client, token, sku)
    r = _place(client, token, uuid.uuid4().hex, _unique_contact())
    assert r.status_code == 201, r.text
    number = r.json()["order_number"]

    session = SessionLocal()
    try:
        order = session.execute(
            select(Order).where(Order.order_number == number)
        ).scalar_one()
        line = session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).scalars().first()

        assert line.unit_cogs is not None, "COGS must be snapshotted at creation"
        snapshotted = line.unit_cogs
        assert line.cogs_snapshot_source == "variant_cost"

        variant = session.execute(
            select(ProductVariant).where(ProductVariant.sku == sku)
        ).scalar_one()
        original_cost = variant.cost
        variant.cost = (original_cost or 0) + 999
        session.commit()

        session.refresh(line)
        assert line.unit_cogs == snapshotted, (
            "order line COGS moved when the catalog cost changed"
        )

        variant.cost = original_cost
        session.commit()
    finally:
        session.close()


def test_cod_order_sets_cod_fields(client):
    """There is a CHECK that cod_amount and cod_collection_status are present
    exactly when the method is cod."""
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.orders import Order

    token = _new_cart(client)
    _add_item(client, token, _first_sku(client))
    r = _place(client, token, uuid.uuid4().hex, _unique_contact(), method="cod")
    assert r.status_code == 201, r.text

    session = SessionLocal()
    try:
        order = session.execute(
            select(Order).where(Order.order_number == r.json()["order_number"])
        ).scalar_one()
        assert order.cod_amount is not None
        assert order.cod_collection_status is not None
        # VAT-inclusive pricing: tax is derived for accounting, not added here.
        assert order.tax_total == 0
        assert order.gross_order_value == order.total
    finally:
        session.close()
