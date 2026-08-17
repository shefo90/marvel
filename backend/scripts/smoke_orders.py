"""End-to-end exercise of idempotent order creation.

Builds a server-side cart (with an attribution trail) directly in the database,
then drives the API with TestClient — no server process, no dependency on the
cart endpoints, so this stays runnable while the cart layer is still moving.

Run from the backend root:  python scripts/smoke_orders.py
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from models.attribution_touches import AttributionTouch  # noqa: E402
from models.attribution_visitors import AttributionVisitor  # noqa: E402
from models.cart_attributions import CartAttribution  # noqa: E402
from models.cart_items import CartItem  # noqa: E402
from models.carts import Cart  # noqa: E402
from models.customer_attributions import CustomerAttribution  # noqa: E402
from models.customers import Customer  # noqa: E402
from models.idempotency_keys import IdempotencyKey  # noqa: E402
from models.order_addresses import OrderAddress  # noqa: E402
from models.order_attributions import OrderAttribution  # noqa: E402
from models.order_audit_log import OrderAuditLog  # noqa: E402
from models.order_items import OrderItem  # noqa: E402
from models.order_status_history import OrderStatusHistory  # noqa: E402
from models.orders import Order  # noqa: E402
from models.product_variants import ProductVariant  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
FAILURES: list[str] = []
RUN = uuid.uuid4().hex[:8]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --- Fixture: a cart with an attribution trail ---------------------------
def make_cart(db, first_campaign: str, last_campaign: str, quantities: list[int]):
    variants = (
        db.execute(
            select(ProductVariant)
            .where(ProductVariant.is_active.is_(True))
            .order_by(ProductVariant.id)
            .limit(len(quantities))
        )
        .scalars()
        .all()
    )
    assert len(variants) == len(quantities), "seed the database first (scripts/seed.py)"

    visitor = AttributionVisitor(
        visitor_token=f"vis-{uuid.uuid4().hex[:16]}",
        ga_client_id=f"GA1.1.{uuid.uuid4().int % 10**10}",
        first_landing_page="/en",
    )
    db.add(visitor)
    db.flush()

    first = AttributionTouch(
        visitor_id=visitor.id,
        utm_source="google",
        utm_medium="organic",
        source="google",
        medium="organic",
        campaign=first_campaign,
        channel_group="organic_search",
        landing_page="/en/products/leather-strap-sandal",
        locale="en",
    )
    last = AttributionTouch(
        visitor_id=visitor.id,
        utm_source="google",
        utm_medium="cpc",
        utm_campaign=last_campaign,
        gclid=f"gclid-{uuid.uuid4().hex[:12]}",
        source="google",
        medium="cpc",
        campaign=last_campaign,
        channel_group="paid_search",
        landing_page="/en/products/woven-flat-sandal",
        locale="en",
        extras={"ttclid": "tt-123"},
    )
    db.add_all([first, last])
    db.flush()

    cart = Cart(token=f"cart-{uuid.uuid4().hex[:16]}", locale="en")
    db.add(cart)
    db.flush()
    db.add(
        CartAttribution(
            cart_id=cart.id,
            visitor_id=visitor.id,
            first_touch_id=first.id,
            last_touch_id=last.id,
        )
    )

    subtotal = Decimal("0.00")
    for variant, quantity in zip(variants, quantities):
        price = variant.sale_price if variant.sale_price is not None else variant.price
        subtotal += price * quantity
        db.add(
            CartItem(
                cart_id=cart.id,
                variant_id=variant.id,
                sku=variant.sku,
                quantity=quantity,
                unit_price_snapshot=variant.price,
                unit_sale_price_snapshot=variant.sale_price,
                added_from_list_id="summer_edit",
                added_from_list_name="Summer Edit",
                added_from_index=0,
            )
        )
    cart.item_count = sum(quantities)
    cart.subtotal = subtotal
    cart.total = subtotal
    db.commit()
    return cart.token, subtotal, [v.sku for v in variants], [v.cost for v in variants]


db = SessionLocal()
token_1, subtotal_1, skus_1, costs_1 = make_cart(
    db, "brand-terms", "summer-sale", [2, 1]
)
EMAIL = f"guest-{RUN}@example.com"
# Unique per run: identity resolution is deliberately durable, so a fixed phone
# would make the second run of this script find the first run's customer and the
# is_new_customer assertion would be testing the fixture, not the code.
PHONE_LOCAL = "01" + f"{uuid.uuid4().int % 10**9:09d}"
PHONE_TYPED = f"{PHONE_LOCAL[:4]} {PHONE_LOCAL[4:7]} {PHONE_LOCAL[7:]}"
PHONE_OTHER_FORMAT = "0020" + PHONE_LOCAL[1:]

BODY = {
    "cart_token": token_1,
    "customer": {
        "email": EMAIL,
        "phone": PHONE_TYPED,
        "first_name": "Nour",
        "last_name": "Hassan",
    },
    "shipping_address": {
        "recipient_name": "Nour Hassan",
        "phone": PHONE_LOCAL,
        "governorate": "Cairo",
        "city": "Nasr City",
        "district": "First Zone",
        "street_address": "12 Abbas El Akkad",
        "building": "7",
        "floor": "3",
        "apartment": "9",
        "landmark": "Next to the pharmacy",
    },
    "payment_method": "cod",
}
KEY = f"idem-{RUN}-1"

print("idempotency preconditions:")
r = client.post("/api/en/orders", json=BODY)
check("missing Idempotency-Key is rejected", r.status_code == 400, r.text[:120])
r = client.post("/api/fr/orders", json=BODY, headers={"Idempotency-Key": KEY})
check("unknown locale 404s", r.status_code == 404, str(r.status_code))

print("\norder creation:")
r1 = client.post("/api/en/orders", json=BODY, headers={"Idempotency-Key": KEY})
check("first request 201", r1.status_code == 201, r1.text[:300])
order = r1.json() if r1.status_code == 201 else {}
if not order:
    print("\nFAILED: order creation did not return a body; aborting")
    sys.exit(1)

number = order["order_number"]
check("order_number is ORD-<n>", number.startswith("ORD-"), number)
check("marked as a first-time customer", order["is_new_customer"] is True)
check("not a replay", r1.headers.get("Idempotent-Replay") == "false")
check("orders are never cached", r1.headers.get("cache-control") == "no-store")

print("\nmoney (VAT-inclusive, tax_total = 0):")
check("tax_total is 0", Decimal(order["tax_total"]) == 0, order["tax_total"])
check(
    "subtotal recomputed from the cart lines",
    Decimal(order["subtotal"]) == subtotal_1,
    f'{order["subtotal"]} vs {subtotal_1}',
)
check(
    "total identity holds",
    Decimal(order["total"])
    == Decimal(order["subtotal"])
    - Decimal(order["discount"])
    + Decimal(order["tax_total"])
    + Decimal(order["shipping"]),
)
check(
    "gross_order_value frozen at total",
    Decimal(order["gross_order_value"]) == Decimal(order["total"]),
)
expected_cogs = sum(
    (cost * qty for cost, qty in zip(costs_1, [2, 1]) if cost is not None),
    Decimal("0.00"),
)
check(
    "items_cogs_total rolled from the line snapshots",
    Decimal(order["items_cogs_total"]) == expected_cogs,
    f'{order["items_cogs_total"]} vs {expected_cogs}',
)

print("\nCOD:")
check("cod_amount = total", Decimal(order["cod_amount"]) == Decimal(order["total"]))
check("cod_collection_status set", order["cod_collection_status"] == "pending")

print("\nline snapshots:")
line = order["items"][0]
check("two lines", len(order["items"]) == 2, str(len(order["items"])))
check("sku snapshotted", line["sku"] == skus_1[0], line["sku"])
check("item_group_id snapshotted", bool(line["item_group_id"]), str(line["item_group_id"]))
check("product_title snapshotted", bool(line["product_title"]), line["product_title"])
check("variant_attributes snapshotted", bool(line["variant_attributes"]), str(line["variant_attributes"]))
check("brand snapshotted", line["brand"] == "Pixi", str(line["brand"]))
check("category_path snapshotted", line["category_path"] == "Shoes > Sandals", str(line["category_path"]))
check("product_url snapshotted", line["product_url"].startswith("/en/products/"), str(line["product_url"]))
check("item_list_id carried from the cart", line["item_list_id"] == "summer_edit", str(line["item_list_id"]))
check("unit_cogs snapshotted", Decimal(line["unit_cogs"]) == costs_1[0], str(line["unit_cogs"]))
check("cogs source recorded", line["cogs_snapshot_source"] == "variant_cost", str(line["cogs_snapshot_source"]))

print("\nattribution snapshot (copied, not joined):")
attr = order["attribution"]
check("first touch preserved separately", attr["first_touch_campaign"] == "brand-terms", str(attr["first_touch_campaign"]))
check("last touch recorded separately", attr["last_touch_campaign"] == "summer-sale", str(attr["last_touch_campaign"]))
check("gclid carried for offline upload", bool(attr["gclid"]), str(attr["gclid"]))
check("ga_client_id carried", bool(attr["ga_client_id"]), str(attr["ga_client_id"]))
check("extras carried", attr["extras"].get("ttclid") == "tt-123", str(attr["extras"]))

print("\nreplay (section 15 'purchase fires once'):")
r2 = client.post("/api/en/orders", json=BODY, headers={"Idempotency-Key": KEY})
check("replay returns the stored status", r2.status_code == 201, str(r2.status_code))
check("replay body is byte-identical", r2.json() == order)
check("replay is flagged", r2.headers.get("Idempotent-Replay") == "true")
check("transaction_id is stable", r2.json()["order_number"] == number)

different = dict(BODY, payment_method="card")
r3 = client.post("/api/en/orders", json=different, headers={"Idempotency-Key": KEY})
check("same key + different body is 409", r3.status_code == 409, r3.text[:160])

r4 = client.post(
    "/api/en/orders", json=BODY, headers={"Idempotency-Key": f"idem-{RUN}-fresh"}
)
check("a converted cart cannot be re-ordered", r4.status_code == 409, r4.text[:160])

print("\ndatabase state:")
db.expire_all()
row = db.execute(select(Order).where(Order.order_number == number)).scalar_one()
check("exactly one order for the cart", db.execute(select(func.count()).select_from(Order).where(Order.cart_id == row.cart_id)).scalar_one() == 1)
check("order_items rows written", db.execute(select(func.count()).select_from(OrderItem).where(OrderItem.order_id == row.id)).scalar_one() == 2)
check("order_attributions snapshot exists", db.get(OrderAttribution, row.id) is not None)
history = db.execute(select(OrderStatusHistory).where(OrderStatusHistory.order_id == row.id)).scalars().all()
check("creation transition logged", len(history) == 1 and history[0].to_status == "pending", str([h.to_status for h in history]))
check("logical_event_id derived from the order number", history[0].logical_event_id == f"{number}:order:pending", str(history[0].logical_event_id))
address = db.execute(select(OrderAddress).where(OrderAddress.order_id == row.id)).scalars().all()
check("shipping address snapshot written", len(address) == 1 and address[0].address_type.value == "shipping")
cart_row = db.get(Cart, row.cart_id)
check("cart marked converted", cart_row.status.value == "converted" and cart_row.converted_order_id == row.id)
idem = db.execute(select(IdempotencyKey).where(IdempotencyKey.scope == "order_create", IdempotencyKey.key == KEY)).scalar_one()
check("idempotency row completed", idem.status == "completed" and idem.completed_at is not None)
check("stored response has the order number", (idem.response_body or {}).get("order_number") == number)
check("idempotency row links the order", idem.order_id == row.id)
check("no audit rows written by Python at creation", db.execute(select(func.count()).select_from(OrderAuditLog).where(OrderAuditLog.order_id == row.id)).scalar_one() == 0)
check("business_date set", row.business_date is not None, str(row.business_date))

print("\nidentity contract (database-enforced):")
try:
    db.execute(text("UPDATE orders SET order_number = 'ORD-HACK' WHERE id = :i"), {"i": row.id})
    db.commit()
    check("order_number is immutable", False, "the UPDATE was accepted")
except Exception as exc:  # noqa: BLE001
    db.rollback()
    check("order_number is immutable", "immutable" in str(exc), str(exc)[:120])

print("\nApproach A audit trigger (money change, attributed via SET LOCAL):")
db.execute(text("SET LOCAL app.actor_user_id = ''"))
db.execute(text("SET LOCAL app.audit_reason = 'courier invoice reconciliation'"))
db.execute(text("SET LOCAL app.audit_source = 'smoke_orders'"))
db.execute(text("UPDATE orders SET shipping_cost = 35.00 WHERE id = :i"), {"i": row.id})
db.commit()
audit = db.execute(select(OrderAuditLog).where(OrderAuditLog.order_id == row.id)).scalars().all()
check("trigger wrote the audit row", len(audit) == 1, str(len(audit)))
check("old_value captured for Ads restatement", audit and audit[0].old_value == "0.00", str(audit[0].old_value if audit else None))
check("reason/source read from SET LOCAL", audit and audit[0].source == "smoke_orders", str(audit[0].source if audit else None))

print("\nreturning customer + write-once first acquisition:")
token_2, subtotal_2, _, _ = make_cart(db, "retargeting", "retargeting-oct", [1])
body_2 = {
    "cart_token": token_2,
    # Same shopper, phone written in a different but equivalent format and no
    # email at all: identity resolution must still land on one customer.
    "customer": {"phone": PHONE_OTHER_FORMAT},
    "shipping_address": BODY["shipping_address"],
    "payment_method": "card",
    "payment_provider": "paymob",
}
r5 = client.post("/api/en/orders", json=body_2, headers={"Idempotency-Key": f"idem-{RUN}-2"})
check("second order created", r5.status_code == 201, r5.text[:300])
order_2 = r5.json()
check("phone normalization resolved the same customer", order_2["customer_public_id"] == order["customer_public_id"], str(order_2["customer_public_id"]))
check("is_new_customer false from order history", order_2["is_new_customer"] is False)
check("card order has no COD fields", order_2["cod_amount"] is None and order_2["cod_collection_status"] is None)
check("order numbers differ", order_2["order_number"] != number)
check("second order's own first touch snapshotted", order_2["attribution"]["first_touch_campaign"] == "retargeting", str(order_2["attribution"]["first_touch_campaign"]))

db.expire_all()
customer = db.execute(select(Customer).where(Customer.email == EMAIL)).scalar_one()
ca = db.get(CustomerAttribution, customer.id)
check("customer first acquisition NOT overwritten by the new campaign", ca.first_touch_campaign == "brand-terms", str(ca.first_touch_campaign))
check("first_touch_locked_at stamped once", ca.first_touch_locked_at is not None)
check("last touch does follow the newest campaign", ca.last_touch_campaign == "retargeting-oct", str(ca.last_touch_campaign))
check("customer order history updated", customer.orders_count == 2, str(customer.orders_count))

print("\norder lookup:")
g = client.get(f"/api/en/orders/{number}", params={"email": EMAIL})
check("lookup with the right email 200s", g.status_code == 200, g.text[:160])
check("lookup returns the same snapshot", g.json()["order_number"] == number)
check("lookup without contact is refused", client.get(f"/api/en/orders/{number}").status_code == 400)
check("lookup with a wrong email 404s", client.get(f"/api/en/orders/{number}", params={"email": "someone@else.com"}).status_code == 404)
check("unknown order number 404s", client.get("/api/en/orders/ORD-999999999", params={"email": EMAIL}).status_code == 404)

db.close()
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("all order checks passed")
