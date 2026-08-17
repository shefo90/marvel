"""Do the two customer-identity normalizers agree?

register.py and order.py each implement email/phone normalization independently.
If they ever disagree, the SAME shopper registering and then checking out
resolves to TWO customer_identity rows and therefore two customers — which
silently breaks section 11A's new-vs-returning classification and every lifetime
value aggregate. Nothing would fail loudly; the numbers would just be wrong.

Run from the backend root:  python scripts/check_identity_parity.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repositories import order as order_repo  # noqa: E402
from repositories import register as register_repo  # noqa: E402

EMAILS = [
    "Shopper@Example.com",
    "  spaced@example.com  ",
    "UPPER@EXAMPLE.COM",
    "dotted.name+tag@gmail.com",
]

PHONES = [
    "01001234567",
    "+20 100 123 4567",
    "0020 100 123 4567",
    "+201001234567",
    "00201001234567",
    "0100 123 4567",
    "201001234567",
]

mismatches = []

print("email:")
for raw in EMAILS:
    a = register_repo.normalize_email(raw)
    b = order_repo._normalize_email(raw)
    ok = a == b
    print(f"  {'OK ' if ok else 'DIFF'} {raw!r:32} register={a!r} order={b!r}")
    if not ok:
        mismatches.append(("email", raw, a, b))

print("\nphone:")
for raw in PHONES:
    a = register_repo.normalize_phone(raw)
    b = order_repo._normalize_phone(raw)
    ok = a == b
    print(f"  {'OK ' if ok else 'DIFF'} {raw!r:32} register={a!r} order={b!r}")
    if not ok:
        mismatches.append(("phone", raw, a, b))

print("\nhash:")
h_a = register_repo.sha256_hex("201001234567")
h_b = order_repo._sha256("201001234567")
print(f"  {'OK ' if h_a == h_b else 'DIFF'} register={h_a[:16]}... order={h_b[:16]}...")
if h_a != h_b:
    mismatches.append(("sha256", "201001234567", h_a, h_b))

# The real question: does one shopper collapse to one identity across both paths?
print("\nsame shopper, both paths:")
variants = ["01001234567", "+20 100 123 4567", "00201001234567"]
reg = {register_repo.normalize_phone(v) for v in variants}
orl = {order_repo._normalize_phone(v) for v in variants}
print(f"  register collapses to: {reg}")
print(f"  order    collapses to: {orl}")
collapsed = len(reg) == 1 and len(orl) == 1 and reg == orl
print(f"  {'OK ' if collapsed else 'DIFF'} one shopper -> one identity: {collapsed}")
if not collapsed:
    mismatches.append(("collapse", str(variants), str(reg), str(orl)))

print()
if mismatches:
    print(f"DIVERGENT: {len(mismatches)} case(s) — the same shopper can become two customers")
    for kind, raw, a, b in mismatches:
        print(f"  {kind}: {raw!r} -> register={a!r} order={b!r}")
    sys.exit(1)
print("normalizers agree on every case (duplication is latent, not active)")
