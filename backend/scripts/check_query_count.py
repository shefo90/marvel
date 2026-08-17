"""Prove the catalog listing is O(1) in queries, not O(n).

Redis is not running locally, so every call is a genuine cache miss and hits
Postgres — which makes this an honest measurement rather than one the cache
flatters.

The listing previously issued two queries per product (variants, then the
primary image). A 24-item page cost 49 round trips, and the cache hid it until a
cold page under load.

Run from the backend root:  python scripts/check_query_count.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event  # noqa: E402

from core.db import Engine, SessionLocal  # noqa: E402
from repositories.product import list_products  # noqa: E402

counter = {"n": 0}


@event.listens_for(Engine, "before_cursor_execute")
def _count(conn, cursor, statement, parameters, context, executemany):
    counter["n"] += 1


def measure(**kwargs) -> tuple[int, int]:
    db = SessionLocal()
    counter["n"] = 0
    try:
        result = list_products(db, **kwargs)
        return counter["n"], result["total"]
    finally:
        db.close()


print("catalog listing query counts (cache cold — Redis is down):\n")

q1, total1 = measure(locale="en", page=1, page_size=24)
print(f"  all products      : {q1} queries for {total1} product(s)")

q2, total2 = measure(locale="en", page=1, page_size=24, collection_slug="summer-edit")
print(f"  collection filter : {q2} queries for {total2} product(s)")

q3, total3 = measure(locale="ar", page=1, page_size=24)
print(f"  arabic listing    : {q3} queries for {total3} product(s)")

print()
# Budget: count + page + variants + images, plus a little slack for the
# category/collection lookup. The point is that it must not scale with n.
BUDGET = 8
failures = []
for label, q, total in [
    ("all products", q1, total1),
    ("collection filter", q2, total2),
    ("arabic listing", q3, total3),
]:
    ok = q <= BUDGET
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {q} <= {BUDGET}")
    if not ok:
        failures.append(label)

print()
if failures:
    print(f"FAILED: {failures} — listing still scales with product count")
    sys.exit(1)
print(f"listing is O(1) in queries (budget {BUDGET})")
