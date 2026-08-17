"""The Approach-A audit trail, and the immutable identifiers.

These are the invariants the money model rests on. Approach A keeps money in
mutable columns, so the audit trigger is the ONLY record of a prior value — and
section 6's Google Ads RETRACTION/RESTATEMENT needs exactly that prior value to
correct a conversion. If the trigger silently stops firing, every dashboard
still renders and nothing errors; the history is just gone.
"""

from sqlalchemy import text


def _make_order(conn, number: str) -> int:
    return conn.execute(
        text("insert into orders (order_number) values (:n) returning id"),
        {"n": number},
    ).scalar_one()


def test_money_change_writes_one_audit_row_per_column(conn):
    oid = _make_order(conn, "ORD-TEST-AUDIT-1")

    conn.execute(
        text(
            "update orders set subtotal=250.00, total=250.00, gross_order_value=250.00 "
            "where id=:i"
        ),
        {"i": oid},
    )

    rows = conn.execute(
        text("select field from order_audit_log where order_id=:i"), {"i": oid}
    ).scalars().all()

    assert set(rows) == {"subtotal", "total", "gross_order_value"}


def test_audit_row_captures_old_value(conn):
    """Without old_value there is no way to issue an Ads RETRACTION."""
    oid = _make_order(conn, "ORD-TEST-AUDIT-2")
    conn.execute(
        text("update orders set subtotal=100.00, total=100.00 where id=:i"), {"i": oid}
    )
    conn.execute(
        text("update orders set subtotal=175.00, total=175.00 where id=:i"), {"i": oid}
    )

    rows = conn.execute(
        text(
            "select old_amount, new_amount from order_audit_log "
            "where order_id=:i and field='total' order by id"
        ),
        {"i": oid},
    ).all()

    assert len(rows) == 2
    assert [str(r[0]) for r in rows] == ["0.00", "100.00"]
    assert [str(r[1]) for r in rows] == ["100.00", "175.00"]


def test_unchanged_value_writes_no_audit_row(conn):
    oid = _make_order(conn, "ORD-TEST-AUDIT-3")
    conn.execute(text("update orders set subtotal=50.00, total=50.00 where id=:i"), {"i": oid})
    before = conn.execute(
        text("select count(*) from order_audit_log where order_id=:i"), {"i": oid}
    ).scalar_one()

    conn.execute(text("update orders set subtotal=50.00 where id=:i"), {"i": oid})

    after = conn.execute(
        text("select count(*) from order_audit_log where order_id=:i"), {"i": oid}
    ).scalar_one()
    assert before == after


def test_staff_actor_is_threaded_from_session(conn):
    """Section 13 requires an admin audit trail for manual changes."""
    oid = _make_order(conn, "ORD-TEST-AUDIT-4")
    conn.execute(text("set local app.audit_reason = 'manual correction'"))
    conn.execute(text("set local app.audit_source = 'admin_ui'"))
    conn.execute(text("update orders set shipping_cost=30.00 where id=:i"), {"i": oid})

    row = conn.execute(
        text(
            "select reason, source, actor_type from order_audit_log "
            "where order_id=:i and field='shipping_cost'"
        ),
        {"i": oid},
    ).one()
    assert row[0] == "manual correction"
    assert row[1] == "admin_ui"
    assert row[2] == "system"  # no actor_user_id set


def test_order_number_is_immutable(conn):
    """Section 2: the transaction_id must never regenerate."""
    import pytest

    oid = _make_order(conn, "ORD-TEST-IMMUTABLE")
    sp = conn.begin_nested()
    with pytest.raises(Exception) as exc:
        conn.execute(
            text("update orders set order_number='ORD-CHANGED' where id=:i"), {"i": oid}
        )
    sp.rollback()
    assert "immutable" in str(exc.value)


def test_variant_sku_is_immutable(conn):
    """The SKU is the sellable identity shared with Merchant and every catalog."""
    import pytest

    vid = conn.execute(
        text("select id from product_variants order by id limit 1")
    ).scalar_one()

    sp = conn.begin_nested()
    with pytest.raises(Exception) as exc:
        conn.execute(
            text("update product_variants set sku='SKU-REWRITTEN' where id=:i"),
            {"i": vid},
        )
    sp.rollback()
    assert "immutable" in str(exc.value)
