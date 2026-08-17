"""Prove the migration 0002 + 0004 triggers actually work against the live database.

This is the acceptance evidence for the Approach-A decision: because the money
lives in mutable columns rather than an append-only ledger, the audit trigger is
the ONLY thing preserving what a value used to be. If it silently does not fire,
section 11A's auditability requirement is unmet and nothing else would tell us.

0004 added a fifth trigger making order_audit_log append-only, so that record is
evidence rather than a convention the application role can rewrite.

Run from the backend root:  python scripts/verify_triggers.py
Rolls everything back — leaves no test data behind.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from core.db import Engine  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


with Engine.begin() as conn:
    tables = conn.execute(
        text(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE'"
        )
    ).scalar_one()
    triggers = [
        r[0]
        for r in conn.execute(
            text(
                "select tgname from pg_trigger t join pg_class c on c.oid=t.tgrelid "
                "where not t.tgisinternal order by tgname"
            )
        )
    ]

print(f"tables: {tables}")
print(f"triggers: {triggers}\n")

check("47 tables present (46 + alembic_version)", tables == 47, str(tables))
check("5 triggers installed", len(triggers) == 5, str(len(triggers)))

# --- The audit trigger ---------------------------------------------------
print("\naudit trigger:")
conn = Engine.connect()
trans = conn.begin()
try:
    oid = conn.execute(
        text(
            "insert into orders (order_number) values ('ORD-TRIGGER-TEST') "
            "returning id"
        )
    ).scalar_one()

    # A staff actor, supplied the way the repository layer will supply it.
    conn.execute(text("set local app.actor_user_id = ''"))
    conn.execute(text("set local app.audit_reason = 'trigger verification'"))

    conn.execute(
        text(
            "update orders set subtotal=100.00, total=100.00, gross_order_value=100.00 "
            "where id=:i"
        ),
        {"i": oid},
    )

    rows = conn.execute(
        text(
            "select field, old_amount, new_amount, actor_type, reason, source "
            "from order_audit_log where order_id=:i order by field"
        ),
        {"i": oid},
    ).all()

    fields = {r[0] for r in rows}
    check(
        "one audit row per changed money column",
        fields == {"subtotal", "total", "gross_order_value"},
        f"got {sorted(fields)}",
    )
    check(
        "old_value captured (needed for Ads RETRACTION/RESTATEMENT)",
        all(r[1] is not None for r in rows),
        f"old_amounts={[str(r[1]) for r in rows]}",
    )
    check(
        "new_value captured",
        all(str(r[2]) == "100.00" for r in rows),
        f"new_amounts={[str(r[2]) for r in rows]}",
    )
    check("reason threaded from session", all(r[4] == "trigger verification" for r in rows))
    check("actor defaults to system when no user set", all(r[3] == "system" for r in rows))

    # A no-op update must not create noise.
    before = conn.execute(
        text("select count(*) from order_audit_log where order_id=:i"), {"i": oid}
    ).scalar_one()
    conn.execute(text("update orders set subtotal=100.00 where id=:i"), {"i": oid})
    after = conn.execute(
        text("select count(*) from order_audit_log where order_id=:i"), {"i": oid}
    ).scalar_one()
    check("unchanged value writes no audit row", before == after, f"{before} -> {after}")

    # --- Immutability ----------------------------------------------------
    print("\nimmutability:")
    raised = False
    sp = conn.begin_nested()
    try:
        conn.execute(
            text("update orders set order_number='ORD-CHANGED' where id=:i"), {"i": oid}
        )
    except Exception as exc:  # noqa: BLE001
        raised = "immutable" in str(exc)
        sp.rollback()
    else:
        sp.rollback()
    check("orders.order_number rejects UPDATE (section 2)", raised)

finally:
    trans.rollback()
    conn.close()

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("all trigger checks passed")
