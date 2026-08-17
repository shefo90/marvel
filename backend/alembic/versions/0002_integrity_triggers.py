"""integrity triggers — identifier immutability and the Approach-A audit trail

Three things the schema alone cannot express:

1. ``orders.order_number`` is immutable. Section 2: the transaction id must
   "never regenerate on refresh". A CHECK constraint cannot compare OLD to NEW,
   so this needs a trigger. With it, the rule is unfalsifiable rather than
   merely documented.

2. ``product_variants.sku`` is immutable, for the same reason — it is the
   sellable identity shared by the dataLayer, GA4/Ads, Merchant and every ad
   catalog. Changing it silently repoints history at a different product.

3. **Every money-column mutation writes an ``order_audit_log`` row.** This is
   the keystone of Approach A. Section 11A requires that "all cost/value
   corrections must be auditable by order_id and timestamp". Because the money
   lives in mutable columns rather than an append-only ledger, the audit row is
   the only record of what a value used to be — and section 6's Google Ads
   RETRACTION/RESTATEMENT needs exactly that original value.

   The trigger deliberately lives in the database, not the repository layer. If
   auditing were application code, one repository function that forgot to log
   would break the chain silently and nothing would fail.

**Actor attribution.** The trigger reads three optional session settings, which
the repository layer sets inside the same transaction:

    SET LOCAL app.actor_user_id = '5'
    SET LOCAL app.audit_reason  = 'courier remittance reconciliation'
    SET LOCAL app.audit_source  = 'reconciliation_job'

When ``app.actor_user_id`` is absent the row is recorded as a system change,
which keeps ``ck_order_audit_log_actor`` satisfied either way.

Revision ID: 0002_integrity_triggers
Revises: 0001_initial_schema
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_integrity_triggers"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION forbid_column_change() RETURNS trigger AS $$
DECLARE
    col text := TG_ARGV[0];
    old_v text;
    new_v text;
BEGIN
    old_v := to_jsonb(OLD) ->> col;
    new_v := to_jsonb(NEW) ->> col;
    IF old_v IS DISTINCT FROM new_v THEN
        RAISE EXCEPTION
            '%.% is immutable (attempted % -> %)',
            TG_TABLE_NAME, col, old_v, new_v
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

AUDIT_FN = """
CREATE OR REPLACE FUNCTION log_money_changes() RETURNS trigger AS $$
DECLARE
    entity_label text := TG_ARGV[0];
    old_j jsonb := to_jsonb(OLD);
    new_j jsonb := to_jsonb(NEW);
    col text;
    ov text;
    nv text;
    target_order_id bigint;
    v_actor_user_id int;
    v_actor_type text;
    v_reason text;
    v_source text;
    i int;
BEGIN
    IF entity_label = 'order' THEN
        target_order_id := NEW.id;
    ELSE
        target_order_id := NEW.order_id;
    END IF;

    v_actor_user_id := nullif(current_setting('app.actor_user_id', true), '')::int;
    v_actor_type := CASE WHEN v_actor_user_id IS NULL THEN 'system' ELSE 'staff' END;
    v_reason := nullif(current_setting('app.audit_reason', true), '');
    v_source := coalesce(nullif(current_setting('app.audit_source', true), ''),
                         'db_trigger');

    FOR i IN 1 .. TG_NARGS - 1 LOOP
        col := TG_ARGV[i];
        ov := old_j ->> col;
        nv := new_j ->> col;

        IF ov IS DISTINCT FROM nv THEN
            INSERT INTO order_audit_log (
                order_id, entity, entity_id, action, field,
                old_value, new_value, old_amount, new_amount, is_monetary,
                reason, actor_type, actor_user_id, source, context,
                occurred_at, recorded_at
            ) VALUES (
                target_order_id, entity_label, NEW.id, 'update', col,
                ov, nv, ov::numeric, nv::numeric, 'Y',
                v_reason, v_actor_type, v_actor_user_id, v_source, '{}'::jsonb,
                now(), now()
            );
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Section 3 + section 11A money columns on orders.
ORDER_MONEY_COLUMNS = [
    "subtotal",
    "discount",
    "tax_total",
    "shipping",
    "total",
    "gross_order_value",
    "items_cogs_total",
    "promotion_cost_total",
    "shipping_cost",
    "cod_amount",
    "cod_remitted_amount",
    "cod_fee",
    "gateway_fee",
    "return_cost_total",
    "refunded_amount_total",
    "net_realized_revenue",
    "contribution_profit",
]

ORDER_ITEM_MONEY_COLUMNS = [
    "unit_price",
    "discount_amount",
    "line_subtotal",
    "tax_amount",
    "line_total",
    "unit_cogs",
    "line_cogs",
    "refunded_amount",
]


def _args(entity: str, columns: list[str]) -> str:
    return ", ".join(f"'{c}'" for c in [entity, *columns])


def upgrade() -> None:
    op.execute(IMMUTABLE_FN)
    op.execute(AUDIT_FN)

    op.execute(
        """
        CREATE TRIGGER trg_orders_order_number_immutable
        BEFORE UPDATE ON orders
        FOR EACH ROW
        WHEN (OLD.order_number IS DISTINCT FROM NEW.order_number)
        EXECUTE FUNCTION forbid_column_change('order_number');
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_variants_sku_immutable
        BEFORE UPDATE ON product_variants
        FOR EACH ROW
        WHEN (OLD.sku IS DISTINCT FROM NEW.sku)
        EXECUTE FUNCTION forbid_column_change('sku');
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_orders_money_audit
        AFTER UPDATE ON orders
        FOR EACH ROW
        EXECUTE FUNCTION log_money_changes({_args('order', ORDER_MONEY_COLUMNS)});
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_order_items_money_audit
        AFTER UPDATE ON order_items
        FOR EACH ROW
        EXECUTE FUNCTION log_money_changes(
            {_args('order_item', ORDER_ITEM_MONEY_COLUMNS)}
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_order_items_money_audit ON order_items;")
    op.execute("DROP TRIGGER IF EXISTS trg_orders_money_audit ON orders;")
    op.execute("DROP TRIGGER IF EXISTS trg_variants_sku_immutable ON product_variants;")
    op.execute("DROP TRIGGER IF EXISTS trg_orders_order_number_immutable ON orders;")
    op.execute("DROP FUNCTION IF EXISTS log_money_changes();")
    op.execute("DROP FUNCTION IF EXISTS forbid_column_change();")
