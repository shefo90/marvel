"""Exercise the cache path with Redis actually UP.

Everything so far ran with Redis down, which only proved the degraded path. This
proves the part that has never been tested: that a warm cache returns the same
answer as a cold one, that locale scoping actually isolates content, and that
invalidation works.

The locale test is the one that matters. If cache keys were not locale-scoped,
the first request would poison the other language — and the bug would look like
"Arabic users randomly see English", which is miserable to diagnose in
production.

Run from the backend root:  python scripts/check_cache_live.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event  # noqa: E402

from core.db import Engine, SessionLocal, redis_client  # noqa: E402
from repositories.product import get_product_by_slug, list_products  # noqa: E402
from services import cache  # noqa: E402

FAILURES: list[str] = []
counter = {"n": 0}


@event.listens_for(Engine, "before_cursor_execute")
def _count(conn, cursor, statement, parameters, context, executemany):
    counter["n"] += 1


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


print("redis:")
check("ping succeeds", cache.ping() is True)

# Start from a clean slate so 'cold' really is cold.
redis_client.flushdb()

db = SessionLocal()
try:
    print("\ncold vs warm:")
    counter["n"] = 0
    cold = get_product_by_slug(db, "en", "leather-strap-sandal")
    cold_q = counter["n"]

    counter["n"] = 0
    warm = get_product_by_slug(db, "en", "leather-strap-sandal")
    warm_q = counter["n"]

    check("cold read hits the database", cold_q > 0, f"{cold_q} queries")
    check("warm read hits zero queries", warm_q == 0, f"{warm_q} queries")
    check("warm result equals cold result", warm == cold)

    print("\nlocale isolation (the dangerous one):")
    ar = get_product_by_slug(db, "ar", "صندل-جلد-بحزام")
    check("arabic read is not the cached english payload", ar is not None and ar["locale"] == "ar")
    check("arabic title is Arabic", ar["title"] == "صندل جلد بحزام", str(ar["title"]))
    en_again = get_product_by_slug(db, "en", "leather-strap-sandal")
    check("english still english after arabic read", en_again["locale"] == "en")

    print("\nkeys actually written:")
    keys = sorted(k for k in redis_client.scan_iter("marvel:*"))
    for k in keys:
        print(f"    {k}")
    check("every key carries a locale segment", all(":en:" in k or ":ar:" in k for k in keys), str(len(keys)))

    print("\ninvalidation:")
    counter["n"] = 0
    list_products(db, locale="en", page=1, page_size=24)
    counter["n"] = 0
    list_products(db, locale="en", page=1, page_size=24)
    check("listing warms too", counter["n"] == 0, f"{counter['n']} queries")

    before = cache.namespace_version(cache.NS_LISTING)
    cache.invalidate_namespace(cache.NS_LISTING)
    after = cache.namespace_version(cache.NS_LISTING)
    check("namespace version bumps", after == before + 1, f"{before} -> {after}")

    counter["n"] = 0
    list_products(db, locale="en", page=1, page_size=24)
    check("listing re-reads the database after invalidation", counter["n"] > 0, f"{counter['n']} queries")

    print("\nTTL policy:")
    pkey = cache.key(cache.NS_PRODUCT, "en", "leather-strap-sandal")
    get_product_by_slug(db, "en", "leather-strap-sandal")
    ttl = redis_client.ttl(pkey)
    check("price-bearing payload has a short TTL", 0 < ttl <= cache.TTL_PRICING, f"{ttl}s")
finally:
    db.close()

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("cache verified with Redis up")
