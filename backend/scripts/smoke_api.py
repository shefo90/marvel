"""End-to-end smoke test of the catalog API against the seeded database.

Uses TestClient, so no server process is needed.
Run from the backend root:  python scripts/smoke_api.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


print("health:")
r = client.get("/health")
check("health 200", r.status_code == 200, str(r.json()))

print("\nlocale routing:")
check("unknown locale 404s", client.get("/api/fr/products").status_code == 404)
check("/api/en/products 200", client.get("/api/en/products").status_code == 200)
check("/api/ar/products 200", client.get("/api/ar/products").status_code == 200)

print("\nlistings:")
en = client.get("/api/en/products").json()
ar = client.get("/api/ar/products").json()
check("english lists both products", en["total"] == 2, f"total={en['total']}")
check(
    "arabic lists only the translated product",
    ar["total"] == 1,
    f"total={ar['total']}",
)
check(
    "arabic title is actually Arabic",
    ar["items"][0]["title"] == "صندل جلد بحزام",
    ar["items"][0]["title"],
)
check(
    "listing carries index for section 5 select_item",
    en["items"][0]["index"] == 0,
    str(en["items"][0]["index"]),
)

print("\ncollection listing (section 5 item_list_id):")
coll = client.get("/api/en/products", params={"collection": "summer-edit"}).json()
check("collection filter works", coll["total"] == 2, f"total={coll['total']}")
check("item_list_id present", coll["item_list_id"] == "summer_edit", str(coll["item_list_id"]))
check("item_list_name present", coll["item_list_name"] == "Summer Edit")

print("\nproduct detail:")
p = client.get("/api/en/products/leather-strap-sandal")
check("english detail 200", p.status_code == 200)
body = p.json()
check("3 variants", len(body["variants"]) == 3, str(len(body["variants"])))
check(
    "sku is the section 2 sellable id",
    body["variants"][0]["sku"].startswith("PX-SANDAL-01-BLA"),
    body["variants"][0]["sku"],
)
check("price is EGP", body["variants"][0]["currency"] == "EGP")
check("cache-control is short", "max-age=60" in p.headers.get("cache-control", ""))

print("\nhreflang cluster:")
check(
    "bilingual product emits both alternates",
    set(body["alternates"]) == {"en", "ar"},
    str(body["alternates"]),
)
ar_p = client.get("/api/ar/products/صندل-جلد-بحزام")
check("arabic slug resolves", ar_p.status_code == 200, str(ar_p.status_code))

solo = client.get("/api/en/products/woven-flat-sandal").json()
check(
    "english-only product emits NO hreflang (cluster of one)",
    solo["alternates"] == {},
    str(solo["alternates"]),
)

print("\nfallback policy:")
check(
    "untranslated product 404s under /ar/ rather than falling back",
    client.get("/api/ar/products/woven-flat-sandal").status_code == 404,
)
check("missing slug 404s", client.get("/api/en/products/nope").status_code == 404)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("all API smoke checks passed")
