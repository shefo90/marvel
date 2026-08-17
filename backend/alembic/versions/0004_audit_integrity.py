"""audit integrity — make the Approach-A trail evidence rather than convention

Four defects found by the adversarial pass recorded in
``docs/superpowers/specs/2026-08-17-s1-audit-findings.md``.

1. **``order_audit_log`` was not append-only.** A row could be rewritten and
   then deleted outright by the same role the API connects as. Because Approach
   A keeps money in mutable columns, this table is the *only* record of a prior
   value — and design section 5.2 rule 3 names it as the source of the original
   conversion value section 6's Google Ads RETRACTION/RESTATEMENT needs. An
   audit table the application can rewrite is a convention, not evidence.

   Deletion is still permitted when the parent order is already gone, which is
   the cascade from deleting the order itself. Those rows describe revenue that
   no longer exists. Deleting a whole order therefore still discards its audit
   rows — but that removes the order from every reconciliation at the same time,
   which is loud. Selective deletion, which is silent, is what this blocks.

2. **``unit_list_price`` was the one order-item money column left unwatched.**
   Eight of nine numeric columns were audited. Design section 5.2 rule 1 says
   *every* money-column mutation writes a row; the pre-discount reference price
   is what per-line discount attribution and GA4's price/discount split are
   computed against.

3. **DELETE wrote no audit row.** Both money triggers were ``AFTER UPDATE``
   only, so an entire revenue line could leave an order silently.

   The DELETE trigger is added to ``order_items`` only. On ``orders`` it would
   be a no-op: ``order_audit_log.order_id`` is ``ON DELETE CASCADE``, so any row
   written while deleting an order is removed by the same statement, and the FK
   would reject it besides.

4. **Three ``is_*`` columns were ``varchar`` holding 'Y'/'N'** while the other
   21 were ``boolean``. ``WHERE is_active`` is a type error against a varchar,
   and ``order_audit_log.is_monetary`` carried no CHECK at all, so it accepted
   any string. Converted while there is no production data; afterwards this
   becomes a data migration.

Revision ID: 0004_audit_integrity
Revises: 0003_portable_slug_check
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004_audit_integrity"
down_revision: Union[str, None] = "0003_portable_slug_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ``NEW`` is NULL in a DELETE trigger, so every access is routed through TG_OP.
AUDIT_FN_V2 = """
CREATE OR REPLACE FUNCTION log_money_changes() RETURNS trigger AS $$
DECLARE
    entity_label text := TG_ARGV[0];
    is_delete boolean := (TG_OP = 'DELETE');
    old_j jsonb := to_jsonb(OLD);
    new_j jsonb;
    col text;
    ov text;
    nv text;
    target_order_id bigint;
    subject_id bigint;
    v_actor_user_id int;
    v_actor_type text;
    v_reason text;
    v_source text;
    i int;
BEGIN
    IF is_delete THEN
        subject_id := OLD.id;
    ELSE
        new_j := to_jsonb(NEW);
        subject_id := NEW.id;
    END IF;

    IF entity_label = 'order' THEN
        target_order_id := subject_id;
    ELSIF is_delete THEN
        target_order_id := OLD.order_id;
    ELSE
        target_order_id := NEW.order_id;
    END IF;

    -- Cascade from deleting the order itself: these rows would be cascade
    -- deleted by the same statement, and the FK would reject them anyway.
    IF is_delete AND NOT EXISTS (SELECT 1 FROM orders WHERE id = target_order_id) THEN
        RETURN OLD;
    END IF;

    v_actor_user_id := nullif(current_setting('app.actor_user_id', true), '')::int;
    v_actor_type := CASE WHEN v_actor_user_id IS NULL THEN 'system' ELSE 'staff' END;
    v_reason := nullif(current_setting('app.audit_reason', true), '');
    v_source := coalesce(nullif(current_setting('app.audit_source', true), ''),
                         'db_trigger');

    FOR i IN 1 .. TG_NARGS - 1 LOOP
        col := TG_ARGV[i];
        ov := old_j ->> col;
        nv := CASE WHEN is_delete THEN NULL ELSE new_j ->> col END;

        IF ov IS DISTINCT FROM nv THEN
            INSERT INTO order_audit_log (
                order_id, entity, entity_id, action, field,
                old_value, new_value, old_amount, new_amount, is_monetary,
                reason, actor_type, actor_user_id, source, context,
                occurred_at, recorded_at
            ) VALUES (
                target_order_id, entity_label, subject_id,
                CASE WHEN is_delete THEN 'delete' ELSE 'update' END, col,
                ov, nv, ov::numeric, nv::numeric, true,
                v_reason, v_actor_type, v_actor_user_id, v_source, '{}'::jsonb,
                now(), now()
            );
        END IF;
    END LOOP;

    IF is_delete THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION forbid_audit_log_rewrite() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'order_audit_log is append-only (attempted UPDATE of row %)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- Permitted only as the cascade from deleting the parent order.
    IF EXISTS (SELECT 1 FROM orders WHERE id = OLD.order_id) THEN
        RAISE EXCEPTION
            'order_audit_log is append-only (attempted DELETE of row % while order % still exists)',
            OLD.id, OLD.order_id
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

ORDER_ITEM_MONEY_COLUMNS = [
    "unit_list_price",  # added in 0004 — was the one unwatched money column
    "unit_price",
    "discount_amount",
    "line_subtotal",
    "tax_amount",
    "line_total",
    "unit_cogs",
    "line_cogs",
    "refunded_amount",
]

# Unchanged from 0002; repeated so the trigger can be recreated against the
# new function without importing across revisions.
ORDER_ITEM_MONEY_COLUMNS_V1 = [c for c in ORDER_ITEM_MONEY_COLUMNS if c != "unit_list_price"]


def _args(entity: str, columns: list[str]) -> str:
    return ", ".join(f"'{c}'" for c in [entity, *columns])


def upgrade() -> None:
    # --- 4. varchar 'Y'/'N' flags become boolean --------------------------
    # The partial unique index predicates on is_active, so it cannot survive the
    # type change and is rebuilt below.
    op.execute("DROP INDEX IF EXISTS uq_shipments_active_per_order;")
    op.execute("ALTER TABLE shipments DROP CONSTRAINT IF EXISTS ck_shipments_is_active;")
    op.execute(
        "ALTER TABLE shipment_status_events "
        "DROP CONSTRAINT IF EXISTS ck_shipment_status_events_is_unmapped;"
    )

    for table, column, default in [
        ("shipments", "is_active", "true"),
        ("shipment_status_events", "is_unmapped", "false"),
        ("order_audit_log", "is_monetary", None),
    ]:
        # A varchar default cannot be cast to boolean automatically.
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE boolean USING ({column} = 'Y');"
        )
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default};")

    op.execute(
        "CREATE UNIQUE INDEX uq_shipments_active_per_order "
        "ON shipments (order_id) WHERE is_active;"
    )

    # --- 2 + 3. money trigger watches unit_list_price and fires on DELETE --
    op.execute(AUDIT_FN_V2)
    op.execute("DROP TRIGGER IF EXISTS trg_order_items_money_audit ON order_items;")
    op.execute(
        f"""
        CREATE TRIGGER trg_order_items_money_audit
        AFTER UPDATE OR DELETE ON order_items
        FOR EACH ROW
        EXECUTE FUNCTION log_money_changes(
            {_args('order_item', ORDER_ITEM_MONEY_COLUMNS)}
        );
        """
    )

    # --- 1. the audit log becomes append-only ------------------------------
    op.execute(APPEND_ONLY_FN)
    op.execute(
        """
        CREATE TRIGGER trg_order_audit_log_append_only
        BEFORE UPDATE OR DELETE ON order_audit_log
        FOR EACH ROW
        EXECUTE FUNCTION forbid_audit_log_rewrite();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_order_audit_log_append_only ON order_audit_log;")
    op.execute("DROP FUNCTION IF EXISTS forbid_audit_log_rewrite();")

    op.execute("DROP TRIGGER IF EXISTS trg_order_items_money_audit ON order_items;")
    op.execute(
        f"""
        CREATE TRIGGER trg_order_items_money_audit
        AFTER UPDATE ON order_items
        FOR EACH ROW
        EXECUTE FUNCTION log_money_changes(
            {_args('order_item', ORDER_ITEM_MONEY_COLUMNS_V1)}
        );
        """
    )

    op.execute("DROP INDEX IF EXISTS uq_shipments_active_per_order;")
    for table, column, default in [
        ("shipments", "is_active", "'Y'"),
        ("shipment_status_events", "is_unmapped", "'N'"),
        ("order_audit_log", "is_monetary", None),
    ]:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE varchar(1) USING (CASE WHEN {column} THEN 'Y' ELSE 'N' END);"
        )
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default};")

    op.execute(
        "ALTER TABLE shipments ADD CONSTRAINT ck_shipments_is_active "
        "CHECK (is_active IN ('Y','N'));"
    )
    op.execute(
        "ALTER TABLE shipment_status_events "
        "ADD CONSTRAINT ck_shipment_status_events_is_unmapped "
        "CHECK (is_unmapped IN ('Y','N'));"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_shipments_active_per_order "
        "ON shipments (order_id) WHERE is_active = 'Y';"
    )

    # log_money_changes is left at v2; it is backward compatible on UPDATE and
    # the v1 trigger above simply never invokes the DELETE path.
