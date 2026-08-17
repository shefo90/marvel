"""End-to-end smoke test of the server-side cart against the seeded database.

Uses TestClient, so no server process is needed.
Run from the backend root:  python scripts/smoke_cart.py

Exercises, in order: cart creation, guest identity via X-Cart-Token, add with
section 5 list attribution, the price snapshot, rapid repeated clicks, replayed
Idempotency-Key, quantity patch, delete, coupon apply/remove, price drift
detection + reprice, cart attribution with first-touch preservation, the
cart_mutations audit trail, ownership/404 behaviour, and the no-store rule.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Arabic assertions print Arabic. A cp1252 console would raise on that and
# take the whole run down after the checks had already passed.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from decimal import Decimal  # noqa: E402
from uuid import uuid4  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from main import app  # noqa: E402
from models.cart_mutations import CartMutation  # noqa: E402
from models.carts import Cart  # noqa: E402
from models.product_variants import ProductVariant  # noqa: E402

client = TestClient(app)
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


db = SessionLocal()
variants = db.execute(
    select(ProductVariant).where(ProductVariant.is_active.is_(True)).order_by(ProductVariant.id)
).scalars().all()
V1, V2 = variants[0], variants[1]
# Plain copies: V1/V2 are live ORM objects, so a later db.commit() expires them
# and they would silently start reporting the *edited* catalog price — which is
# exactly the value the drift test must not compare against.
V1_PRICE, V2_PRICE = Decimal(V1.price), Decimal(V2.price)
V1_ID, V2_ID, V1_SKU, V2_SKU = V1.id, V2.id, V1.sku, V2.sku
print(f"using variants: {V1_SKU} ({V1_PRICE}) and {V2_SKU} ({V2_PRICE})")


def hdr(token=None, key=None):
    h = {}
    if token:
        h["X-Cart-Token"] = token
    if key:
        h["Idempotency-Key"] = key
    return h


print("\ncart creation:")
r = client.post("/api/en/cart", json={})
check("POST /cart 201/200", r.status_code == 200, str(r.status_code))
cart = r.json()
TOKEN = cart["token"]
check("issues an opaque token", bool(TOKEN) and len(TOKEN) > 20)
check("starts empty", cart["item_count"] == 0 and cart["items"] == [])
check("currency is EGP", cart["currency"] == "EGP")
check("never cached", r.headers.get("cache-control") == "no-store", str(r.headers.get("cache-control")))
check("unknown locale 404s", client.post("/api/fr/cart", json={}).status_code == 404)

print("\nre-POST with the token returns the SAME cart (no duplicate):")
r = client.post("/api/en/cart", json={}, headers=hdr(TOKEN))
check("same token returned", r.json()["token"] == TOKEN)

print("\nGET before/after:")
check("GET without a token 404s", client.get("/api/en/cart").status_code == 404)
check("GET with the token 200s", client.get("/api/en/cart", headers=hdr(TOKEN)).status_code == 200)
check("bogus token 404s", client.get("/api/en/cart", headers=hdr("nope-nope-nope")).status_code == 404)

print("\nadd item with section 5 list attribution:")
r = client.post(
    "/api/en/cart/items",
    headers=hdr(TOKEN),
    json={
        "sku": V1_SKU,
        "quantity": 2,
        "added_from_list_id": "summer_edit",
        "added_from_list_name": "Summer Edit",
        "added_from_index": 3,
    },
)
check("add 200", r.status_code == 200, r.text[:200])
cart = r.json()
line = cart["items"][0]
check("line quantity is 2", line["quantity"] == 2, str(line["quantity"]))
check("sku is the section 2 identity", line["sku"] == V1_SKU, line["sku"])
check("item_list_id stored", line["added_from_list_id"] == "summer_edit")
check("item_list_name stored", line["added_from_list_name"] == "Summer Edit")
check("item_list index stored", line["added_from_index"] == 3)
check(
    "price snapshot taken from catalog",
    Decimal(str(line["unit_price_snapshot"])) == V1_PRICE,
    f'{line["unit_price_snapshot"]} vs {V1_PRICE}',
)
check(
    "totals recomputed from snapshots",
    Decimal(str(cart["total"])) == V1_PRICE * 2,
    f'{cart["total"]} vs {V1_PRICE * 2}',
)
check("item_count is the unit count", cart["item_count"] == 2, str(cart["item_count"]))
check("logical_event_id issued", cart["logical_event_id"].startswith("add_to_cart_"), str(cart["logical_event_id"]))

print("\nrapid repeated clicks (5 unkeyed adds of qty 1 must sum to exactly 5):")
for _ in range(5):
    client.post("/api/en/cart/items", headers=hdr(TOKEN), json={"variant_id": V2_ID, "quantity": 1})
cart = client.get("/api/en/cart", headers=hdr(TOKEN)).json()
v2_line = next(i for i in cart["items"] if i["variant_id"] == V2_ID)
check("one line, not five", len([i for i in cart["items"] if i["variant_id"] == V2_ID]) == 1)
check("quantity summed to 5", v2_line["quantity"] == 5, str(v2_line["quantity"]))
expected_total = V1_PRICE * 2 + V2_PRICE * 5
check(
    "value correct after repeated clicks",
    Decimal(str(cart["total"])) == expected_total,
    f'{cart["total"]} vs {expected_total}',
)

print("\nidempotency (same Idempotency-Key replayed 3x):")
KEY = "click-abc-123"
first = client.post(
    "/api/en/cart/items", headers=hdr(TOKEN, KEY), json={"variant_id": V2_ID, "quantity": 1}
).json()
check("first application is not a replay", first["replayed"] is False)
replays = [
    client.post(
        "/api/en/cart/items", headers=hdr(TOKEN, KEY), json={"variant_id": V2_ID, "quantity": 1}
    ).json()
    for _ in range(3)
]
check("replays are flagged", all(x["replayed"] for x in replays))
check(
    "replay returns the ORIGINAL logical_event_id",
    all(x["logical_event_id"] == first["logical_event_id"] for x in replays),
)
check(
    "replay is a no-op on quantity",
    all(
        next(i for i in x["items"] if i["variant_id"] == V2_ID)["quantity"] == 6
        for x in replays
    ),
    str([next(i for i in x["items"] if i["variant_id"] == V2_ID)["quantity"] for x in replays]),
)
check(
    "replay is a no-op on value",
    all(Decimal(str(x["total"])) == V1_PRICE * 2 + V2_PRICE * 6 for x in replays),
)

print("\nPATCH quantity:")
r = client.patch(f"/api/en/cart/items/{V2_ID}", headers=hdr(TOKEN), json={"quantity": 3})
cart = r.json()
check("patch 200", r.status_code == 200, r.text[:200])
check(
    "absolute quantity applied",
    next(i for i in cart["items"] if i["variant_id"] == V2_ID)["quantity"] == 3,
)
check(
    "total follows the patch",
    Decimal(str(cart["total"])) == V1_PRICE * 2 + V2_PRICE * 3,
    str(cart["total"]),
)
check(
    "patching a variant not in the cart 404s",
    client.patch("/api/en/cart/items/999999", headers=hdr(TOKEN), json={"quantity": 1}).status_code
    == 404,
)

print("\nover-stock guard:")
r = client.post(
    "/api/en/cart/items", headers=hdr(TOKEN), json={"variant_id": V1_ID, "quantity": 99}
)
check("exceeding stock 409s", r.status_code == 409, f"{r.status_code} {r.text[:120]}")
after = client.get("/api/en/cart", headers=hdr(TOKEN)).json()
check(
    "rejected add left the cart untouched",
    next(i for i in after["items"] if i["variant_id"] == V1_ID)["quantity"] == 2,
)

print("\nDELETE:")
r = client.delete(f"/api/en/cart/items/{V2_ID}", headers=hdr(TOKEN))
cart = r.json()
check("delete 200", r.status_code == 200)
check("line gone", all(i["variant_id"] != V2_ID for i in cart["items"]))
check("total back to the remaining line", Decimal(str(cart["total"])) == V1_PRICE * 2, str(cart["total"]))

print("\ncoupon:")
r = client.post("/api/en/cart/coupon", headers=hdr(TOKEN), json={"code": "summer10"})
check("coupon applied and normalized", r.json()["coupon_code"] == "SUMMER10", str(r.json()["coupon_code"]))
check(
    "malformed coupon 400s",
    client.post("/api/en/cart/coupon", headers=hdr(TOKEN), json={"code": "a b"}).status_code == 400,
)
r = client.post("/api/en/cart/coupon", headers=hdr(TOKEN), json={"code": None})
check("coupon removed", r.json()["coupon_code"] is None)

print("\nprice drift + reprice:")
db.execute(
    text("UPDATE product_variants SET price = price + 100 WHERE id = :i"), {"i": V1_ID}
)
db.commit()
cart = client.get("/api/en/cart", headers=hdr(TOKEN)).json()
line = next(i for i in cart["items"] if i["variant_id"] == V1_ID)
check("drift detected", line["price_changed"] is True)
check(
    "cart still charges the SNAPSHOT, not the new price",
    Decimal(str(cart["total"])) == V1_PRICE * 2,
    f'{cart["total"]} vs snapshot {V1_PRICE * 2}',
)
r = client.post("/api/en/cart/reprice", headers=hdr(TOKEN))
cart = r.json()
line = next(i for i in cart["items"] if i["variant_id"] == V1_ID)
check("reprice clears the drift flag", line["price_changed"] is False)
check("last_repriced_at stamped", line["last_repriced_at"] is not None)
check(
    "total adopts the new price",
    Decimal(str(cart["total"])) == (V1_PRICE + 100) * 2,
    f'{cart["total"]} vs {(V1_PRICE + 100) * 2}',
)
db.execute(text("UPDATE product_variants SET price = price - 100 WHERE id = :i"), {"i": V1_ID})
db.commit()

print("\nattribution (section 4: cart is the durable carrier):")
r = client.post(
    "/api/en/cart/attribution",
    headers=hdr(TOKEN),
    json={
        "attribution": {
            "visitor_token": "vis-smoke-001",
            "ga_client_id": "GA1.1.111.222",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "summer-launch",
            "gclid": "EAIaIQ-first",
            "landing_page": "/en/products/leather-strap-sandal",
        }
    },
)
attr = r.json()["attribution"]
check("attribution attached", attr is not None and attr["first_touch_id"] is not None)
check("visitor linked", attr["visitor_token"] == "vis-smoke-001")
check("first touch campaign recorded", attr["first_touch_campaign"] == "summer-launch")
check("first==last on a single touch", attr["first_touch_id"] == attr["last_touch_id"])
first_touch_id = attr["first_touch_id"]

r = client.post(
    "/api/en/cart/attribution",
    headers=hdr(TOKEN),
    json={
        "attribution": {
            "visitor_token": "vis-smoke-001",
            "utm_source": "facebook",
            "utm_medium": "paid_social",
            "utm_campaign": "retargeting",
        }
    },
)
attr = r.json()["attribution"]
check(
    "second touch does NOT overwrite first (section 11A)",
    attr["first_touch_id"] == first_touch_id and attr["first_touch_campaign"] == "summer-launch",
    str(attr),
)
check("last touch advances", attr["last_touch_campaign"] == "retargeting")
check("last touch is a new row", attr["last_touch_id"] != first_touch_id)

print("\ncart_mutations audit trail:")
cart_row = db.execute(select(Cart).where(Cart.token == TOKEN)).scalar_one()
muts = db.execute(
    select(CartMutation).where(CartMutation.cart_id == cart_row.id).order_by(CartMutation.id)
).scalars().all()
kinds = [m.mutation_type for m in muts]
check("append-only rows written", len(muts) >= 10, f"{len(muts)} rows: {kinds}")
check("exactly one row for the replayed key", sum(1 for m in muts if m.idempotency_key == KEY) == 1)
check("every row carries a logical_event_id", all(m.logical_event_id for m in muts))
check("logical_event_ids are unique", len({m.logical_event_id for m in muts}) == len(muts))
check(
    "GA4-shaped event names",
    all(m.logical_event_id.startswith(("add_to_cart_", "remove_from_cart_", "update_cart_", "select_promotion_", "cart_reprice_", "cart_merge_")) for m in muts),
    str([m.logical_event_id.rsplit("_", 1)[0] for m in muts]),
)
check("coupon mutations logged", "apply_coupon" in kinds and "remove_coupon" in kinds, str(kinds))
check("reprice mutation logged", "reprice" in kinds)
check(
    "header agrees with its lines",
    cart_row.item_count == sum(i["quantity"] for i in cart["items"]),
    f'{cart_row.item_count} vs {sum(i["quantity"] for i in cart["items"])}',
)

print("\nisolation between two guests:")
other = client.post("/api/en/cart", json={}).json()
check("a second guest gets a different cart", other["token"] != TOKEN)
check("and an empty one", other["item_count"] == 0)

print("\nlocale:")
ar = client.get("/api/ar/cart", headers=hdr(TOKEN)).json()
check("cart follows the locale path segment", ar["locale"] == "ar", ar["locale"])
check(
    "arabic read returns the arabic title",
    ar["items"][0]["title"] == "صندل جلد بحزام",
    str(ar["items"][0]["title"]),
)

print("\nTRUE concurrency — 8 threads, no idempotency key, same variant:")
burst_token = client.post("/api/en/cart", json={}).json()["token"]
with ThreadPoolExecutor(max_workers=8) as pool:
    codes = list(
        pool.map(
            lambda _: client.post(
                "/api/en/cart/items",
                headers=hdr(burst_token),
                json={"variant_id": V2_ID, "quantity": 1},
            ).status_code,
            range(8),
        )
    )
burst = client.get("/api/en/cart", headers=hdr(burst_token)).json()
check("all 8 parallel adds succeeded", set(codes) == {200}, str(codes))
check("collapsed to ONE line", len(burst["items"]) == 1, str(len(burst["items"])))
check("quantity is exactly 8", burst["items"][0]["quantity"] == 8, str(burst["items"][0]["quantity"]))
check(
    "value is exactly 8x the unit price",
    Decimal(str(burst["total"])) == V2_PRICE * 8,
    f'{burst["total"]} vs {V2_PRICE * 8}',
)

print("\nTRUE concurrency — 8 threads sharing ONE Idempotency-Key:")
burst2_token = client.post("/api/en/cart", json={}).json()["token"]
with ThreadPoolExecutor(max_workers=8) as pool:
    bodies = list(
        pool.map(
            lambda _: client.post(
                "/api/en/cart/items",
                headers=hdr(burst2_token, "race-key-001"),
                json={"variant_id": V2_ID, "quantity": 1},
            ).json(),
            range(8),
        )
    )
burst2 = client.get("/api/en/cart", headers=hdr(burst2_token)).json()
check("exactly one request applied", sum(1 for b in bodies if not b["replayed"]) == 1, str([b["replayed"] for b in bodies]))
check("quantity is 1, not 8", burst2["items"][0]["quantity"] == 1, str(burst2["items"][0]["quantity"]))
burst2_row = db.execute(select(Cart).where(Cart.token == burst2_token)).scalar_one()
check(
    "exactly one cart_mutations row for the key",
    db.execute(
        select(func.count())
        .select_from(CartMutation)
        .where(CartMutation.cart_id == burst2_row.id, CartMutation.idempotency_key == "race-key-001")
    ).scalar_one()
    == 1,
)

print("\nsigned-in shopper: claim + merge (open question 6 rule = sum quantities):")
email = f"smoke.cart.{uuid4().hex[:10]}@example.com"
reg = client.post(
    "/api/en/auth/register", json={"email": email, "password": "sup3rsecret!", "phone": None}
)
check("shopper registered", reg.status_code == 201, f"{reg.status_code} {reg.text[:150]}")
tok = client.post("/api/en/auth/login", json={"email": email, "password": "sup3rsecret!"})
check("shopper logged in", tok.status_code == 200, f"{tok.status_code} {tok.text[:150]}")
auth = {"Authorization": f"Bearer {tok.json()['access_token']}"}

guest_a = client.post("/api/en/cart", json={}).json()["token"]
client.post("/api/en/cart/items", headers=hdr(guest_a), json={"variant_id": V1_ID, "quantity": 2})
claimed = client.post("/api/en/cart", json={}, headers={**hdr(guest_a), **auth}).json()
check("guest cart is claimed, not replaced", claimed["token"] == guest_a, claimed["token"])

guest_b = client.post("/api/en/cart", json={}).json()["token"]
client.post("/api/en/cart/items", headers=hdr(guest_b), json={"variant_id": V1_ID, "quantity": 1})
client.post("/api/en/cart/items", headers=hdr(guest_b), json={"variant_id": V2_ID, "quantity": 4})
merged = client.post("/api/en/cart", json={}, headers={**hdr(guest_b), **auth}).json()
check("merged into the shopper's existing cart", merged["token"] == guest_a, merged["token"])
check(
    "colliding variant summed 2+1=3",
    next(i for i in merged["items"] if i["variant_id"] == V1_ID)["quantity"] == 3,
    str(next(i for i in merged["items"] if i["variant_id"] == V1_ID)["quantity"]),
)
check(
    "non-colliding variant carried over",
    next(i for i in merged["items"] if i["variant_id"] == V2_ID)["quantity"] == 4,
)
check(
    "merge is logged in cart_mutations",
    db.execute(
        select(func.count())
        .select_from(CartMutation)
        .join(Cart, Cart.id == CartMutation.cart_id)
        .where(Cart.token == guest_a, CartMutation.mutation_type == "merge")
    ).scalar_one()
    == 1,
)
check("source cart was retired", db.execute(select(Cart.status).where(Cart.token == guest_b)).scalar_one() == "expired")

by_auth = client.get("/api/en/cart", headers=auth)
check("shopper's cart is found with no cart token at all", by_auth.status_code == 200 and by_auth.json()["token"] == guest_a)
check(
    "a bare cart token can no longer reach a claimed cart",
    client.get("/api/en/cart", headers=hdr(guest_a)).status_code == 403,
    str(client.get("/api/en/cart", headers=hdr(guest_a)).status_code),
)

db.close()

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("all cart smoke checks passed")
