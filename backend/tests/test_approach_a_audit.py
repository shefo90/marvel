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


# --------------------------------------------------------------------------
# The audit trail must itself be evidence, not just a convention.
#
# Approach A keeps money in mutable columns, so order_audit_log is the sole
# record of a prior value. An audit table the application role can rewrite is
# not an audit trail. See docs/superpowers/specs/2026-08-17-s1-audit-findings.md
# --------------------------------------------------------------------------


def _make_order_item(conn, order_id: int) -> int:
    """One order line against whatever variant the seed data provides."""
    variant = conn.execute(
        text("select id, sku, product_id from product_variants order by id limit 1")
    ).one()
    return conn.execute(
        text(
            "insert into order_items (order_id, line_number, product_id, variant_id, sku, "
            "                         product_title, unit_list_price, unit_price, quantity, "
            "                         line_subtotal, line_total) "
            "values (:o, 1, :p, :v, :s, 'Test line', 150.00, 100.00, 1, 100.00, 100.00) "
            "returning id"
        ),
        {"o": order_id, "p": variant.product_id, "v": variant.id, "s": variant.sku},
    ).scalar_one()


def test_audit_row_cannot_be_rewritten(conn):
    """Rewriting old_amount would forge the value an Ads RETRACTION reports."""
    import pytest

    oid = _make_order(conn, "ORD-TEST-APPEND-1")
    conn.execute(text("update orders set subtotal=100.00, total=100.00 where id=:i"), {"i": oid})
    aid = conn.execute(
        text("select id from order_audit_log where order_id=:i order by id limit 1"), {"i": oid}
    ).scalar_one()

    sp = conn.begin_nested()
    with pytest.raises(Exception) as exc:
        conn.execute(
            text("update order_audit_log set old_amount=1, new_amount=2 where id=:a"), {"a": aid}
        )
    sp.rollback()
    assert "append-only" in str(exc.value)


def test_audit_row_cannot_be_deleted_while_its_order_exists(conn):
    """Selective deletion is the simplest way to erase an inconvenient correction."""
    import pytest

    oid = _make_order(conn, "ORD-TEST-APPEND-2")
    conn.execute(text("update orders set subtotal=100.00, total=100.00 where id=:i"), {"i": oid})
    aid = conn.execute(
        text("select id from order_audit_log where order_id=:i order by id limit 1"), {"i": oid}
    ).scalar_one()

    sp = conn.begin_nested()
    with pytest.raises(Exception) as exc:
        conn.execute(text("delete from order_audit_log where id=:a"), {"a": aid})
    sp.rollback()
    assert "append-only" in str(exc.value)


def test_unit_list_price_change_is_audited(conn):
    """The pre-discount reference price is a money column like any other.

    Design section 5.2 rule 1: *every* money-column mutation writes an audit row.
    """
    oid = _make_order(conn, "ORD-TEST-LISTPRICE")
    item_id = _make_order_item(conn, oid)

    conn.execute(
        text("update order_items set unit_list_price=999.00 where id=:i"), {"i": item_id}
    )

    row = conn.execute(
        text(
            "select old_amount, new_amount from order_audit_log "
            "where order_id=:o and field='unit_list_price'"
        ),
        {"o": oid},
    ).one()
    assert str(row[0]) == "150.00"
    assert str(row[1]) == "999.00"


def test_deleting_an_order_item_is_audited(conn):
    """A revenue line must not be able to leave an order without a trace."""
    oid = _make_order(conn, "ORD-TEST-ITEMDELETE")
    item_id = _make_order_item(conn, oid)

    conn.execute(text("delete from order_items where id=:i"), {"i": item_id})

    rows = conn.execute(
        text(
            "select field, old_amount, new_amount from order_audit_log "
            "where order_id=:o and action='delete' order by field"
        ),
        {"o": oid},
    ).all()

    fields = {r[0] for r in rows}
    assert "line_total" in fields, "deleting a line must record the revenue removed"
    line_total = next(r for r in rows if r[0] == "line_total")
    assert str(line_total[1]) == "100.00"
    assert line_total[2] is None


def test_boolean_flags_are_actually_boolean(conn):
    """21 of 24 is_* columns are boolean; these three were varchar 'Y'/'N'.

    `WHERE is_active` is a type error against varchar, and is_monetary carried
    no CHECK constraint at all.
    """
    rows = conn.execute(
        text(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema='public' and (table_name, column_name) in "
            "(('shipments','is_active'), ('shipment_status_events','is_unmapped'), "
            " ('order_audit_log','is_monetary'))"
        )
    ).all()

    assert len(rows) == 3
    for table, column, data_type in rows:
        assert data_type == "boolean", f"{table}.{column} is {data_type}, expected boolean"
