"""Adversarial pass on Approach A (typed money columns + trigger-written audit rows).

Every probe runs inside ONE transaction that is rolled back at the end, so the
database is left exactly as found. Each probe states what it attacked and what
the money model actually did about it.
"""
import psycopg2, textwrap

conn = psycopg2.connect(host="localhost", port=5433, user="marvel", password="marvel", dbname="marvel")
conn.autocommit = False
cur = conn.cursor()
results = []


def rec(pid, attack, expected, observed, verdict):
    results.append((pid, attack, expected, observed, verdict))


def audit_count(order_id, field=None):
    if field:
        cur.execute("SELECT count(*) FROM order_audit_log WHERE order_id=%s AND field=%s", (order_id, field))
    else:
        cur.execute("SELECT count(*) FROM order_audit_log WHERE order_id=%s", (order_id,))
    return cur.fetchone()[0]


# ---------------------------------------------------------------- fixtures
cur.execute("SELECT count(*) FROM orders")
print("existing orders:", cur.fetchone()[0])

cur.execute("INSERT INTO locales (code,hreflang,name_native,text_direction,is_default,is_active,sort_order) "
            "VALUES ('en','en','English','ltr',true,true,1) ON CONFLICT DO NOTHING")
cur.execute("""INSERT INTO categories (parent_id,level,name,slug,list_id,position,is_active,
                                       is_indexable,content_updated_at,created_at,updated_at)
               VALUES (NULL,1,'ProbeTop','probe-cat-top-adv','probe_cat_top_adv',1,true,true,now(),now(),now())
               RETURNING id""")
parent_cat_id = cur.fetchone()[0]
cur.execute("""INSERT INTO categories (parent_id,level,name,slug,list_id,position,is_active,
                                       is_indexable,content_updated_at,created_at,updated_at)
               VALUES (%s,2,'Probe','probe-cat-adv','probe_cat_adv',1,true,true,now(),now(),now())
               RETURNING id""", (parent_cat_id,))
cat_id = cur.fetchone()[0]

cur.execute("""INSERT INTO products (item_group_id,slug,title,brand,category_id,tags,
                                     condition,status,is_indexable,content_updated_at,created_at,updated_at)
               VALUES ('PROBEADV','probe-adv','Probe','Pixi',%s,'{}','new','draft',true,now(),now(),now())
               RETURNING id""", (cat_id,))
prod_id = cur.fetchone()[0]

cur.execute("""INSERT INTO product_variants (product_id,sku,variant_title,attributes,price,currency,
                                             availability,stock_quantity,inventory_updated_at,
                                             merchant_eligible,is_active,catalog_updated_at,created_at,updated_at)
               VALUES (%s,'PROBE-ADV-1','Probe V','{}',100.00,'EGP','in_stock',5,now(),true,true,now(),now(),now())
               RETURNING id""", (prod_id,))
var_id = cur.fetchone()[0]

cur.execute("""INSERT INTO customers (public_id,status,email,orders_count,delivered_orders_count,
                                      lifetime_gross_ordered_revenue,lifetime_delivered_revenue,
                                      lifetime_net_revenue,lifetime_contribution_profit,created_at,updated_at)
               VALUES (gen_random_uuid(),'active','probe.adv@example.com',0,0,0,0,0,0,now(),now())
               RETURNING id""")
cust_id = cur.fetchone()[0]

cur.execute("""INSERT INTO orders (order_number,customer_id,status,locale,currency,subtotal,discount,
                                   tax_total,shipping,total,gross_order_value,payment_status,payment_method,
                                   items_cogs_total,promotion_cost_total,shipping_cost,cod_fee,gateway_fee,
                                   return_cost_total,refunded_amount_total,placed_at,created_at,updated_at)
               VALUES ('PROBE-ADV-0001',%s,'pending','en','EGP',100,0,0,20,120,120,'pending','card',
                       0,0,0,0,0,0,0,now(),now(),now())
               RETURNING id""", (cust_id,))
order_id = cur.fetchone()[0]

cur.execute("""INSERT INTO order_items (order_id,line_number,product_id,variant_id,sku,product_title,
                                        variant_attributes,unit_list_price,unit_price,quantity,
                                        discount_amount,line_subtotal,tax_amount,line_total,
                                        refunded_quantity,refunded_amount,restocked_quantity,
                                        created_at,updated_at)
               VALUES (%s,1,%s,%s,'PROBE-ADV-1','Probe','{}',150.00,100.00,1,0,100,0,100,0,0,0,now(),now())
               RETURNING id""", (order_id, prod_id, var_id))
item_id = cur.fetchone()[0]
conn.commit()  # fixtures committed so triggers see a real prior row; cleaned up at the end

# ------------------------------------------------- P1: unit_list_price audited?
before = audit_count(order_id, 'unit_list_price')
cur.execute("UPDATE order_items SET unit_list_price=999.00 WHERE id=%s", (item_id,))
after = audit_count(order_id, 'unit_list_price')
rec("P1", "UPDATE order_items.unit_list_price 150 -> 999 (a money column)",
    "an order_audit_log row capturing the old value",
    f"{after - before} audit rows written",
    "GAP" if after == before else "OK")

# ------------------------------------------------- P2: watched column audited?
before = audit_count(order_id, 'line_total')
cur.execute("UPDATE order_items SET line_total=555.00 WHERE id=%s", (item_id,))
after = audit_count(order_id, 'line_total')
rec("P2", "UPDATE order_items.line_total 100 -> 555 (a watched money column)",
    "an order_audit_log row", f"{after - before} audit rows written",
    "OK" if after > before else "GAP")

# ------------------------------------------------- P3: unattributed staff edit
cur.execute("UPDATE orders SET total=140.00, shipping=40.00 WHERE id=%s", (order_id,))
cur.execute("SELECT actor_type, actor_user_id, source FROM order_audit_log "
            "WHERE order_id=%s AND field='total' ORDER BY id DESC LIMIT 1", (order_id,))
row = cur.fetchone()
rec("P3", "UPDATE orders.total with no SET LOCAL app.actor_user_id (forgot the convention)",
    "the change is attributable to a person, or is refused",
    f"recorded as actor_type={row[0]!r}, actor_user_id={row[1]!r}, source={row[2]!r}",
    "RESIDUAL RISK")

# ------------------------------------------------- P4/P5: immutability
for probe, sql, params, label in [
    ("P4", "UPDATE orders SET order_number='HACKED' WHERE id=%s", (order_id,), "orders.order_number"),
    ("P5", "UPDATE product_variants SET sku='HACKED-1' WHERE id=%s", (var_id,), "product_variants.sku"),
]:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
        cur.execute("RELEASE SAVEPOINT sp")
        rec(probe, f"UPDATE {label} (identifier GA4/Ads/Merchant key on)",
            "rejected by trigger", "*** ACCEPTED ***", "GAP")
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        rec(probe, f"UPDATE {label} (identifier GA4/Ads/Merchant key on)",
            "rejected by trigger", f"rejected: {str(e).splitlines()[0][:70]}", "OK")

# ------------------------------------------------- P6: tamper with the audit log
cur.execute("SELECT id FROM order_audit_log WHERE order_id=%s ORDER BY id DESC LIMIT 1", (order_id,))
audit_id = cur.fetchone()[0]
cur.execute("SAVEPOINT sp2")
try:
    cur.execute("UPDATE order_audit_log SET old_amount=0, new_amount=0, old_value='0', new_value='0' "
                "WHERE id=%s", (audit_id,))
    cur.execute("DELETE FROM order_audit_log WHERE id=%s", (audit_id,))
    cur.execute("SELECT count(*) FROM order_audit_log WHERE id=%s", (audit_id,))
    gone = cur.fetchone()[0] == 0
    cur.execute("RELEASE SAVEPOINT sp2")
    rec("P6", "Rewrite then DELETE an order_audit_log row (tamper with the evidence)",
        "audit rows are append-only / tamper-evident",
        f"UPDATE accepted; DELETE accepted (row gone: {gone})", "GAP")
except psycopg2.Error as e:
    cur.execute("ROLLBACK TO SAVEPOINT sp2")
    rec("P6", "Rewrite then DELETE an order_audit_log row",
        "audit rows are append-only", f"rejected: {str(e).splitlines()[0][:70]}", "OK")

# ------------------------------------------------- P7: gross_order_value drift
cur.execute("SAVEPOINT sp3")
try:
    cur.execute("UPDATE orders SET gross_order_value=999999.00 WHERE id=%s", (order_id,))
    cur.execute("SELECT total, gross_order_value FROM orders WHERE id=%s", (order_id,))
    t, g = cur.fetchone()
    cur.execute("RELEASE SAVEPOINT sp3")
    rec("P7", "Set orders.gross_order_value far away from orders.total",
        "constrained to agree with the order value at creation",
        f"accepted: total={t}, gross_order_value={g} (audited, but unconstrained)", "GAP")
except psycopg2.Error as e:
    cur.execute("ROLLBACK TO SAVEPOINT sp3")
    rec("P7", "Set orders.gross_order_value far away from orders.total",
        "constrained", f"rejected: {str(e).splitlines()[0][:70]}", "OK")

# ------------------------------------------------- P8: total identity guard
cur.execute("SAVEPOINT sp4")
try:
    cur.execute("UPDATE orders SET total=1.00 WHERE id=%s", (order_id,))
    cur.execute("RELEASE SAVEPOINT sp4")
    rec("P8", "Set orders.total so it no longer equals subtotal-discount+tax+shipping",
        "rejected by ck_orders_total_identity", "*** ACCEPTED ***", "GAP")
except psycopg2.Error as e:
    cur.execute("ROLLBACK TO SAVEPOINT sp4")
    rec("P8", "Set orders.total so it no longer equals subtotal-discount+tax+shipping",
        "rejected by ck_orders_total_identity", f"rejected: {str(e).splitlines()[0][:60]}", "OK")

# ------------------------------------------------- P9: negative money via discount
cur.execute("SAVEPOINT sp5")
try:
    cur.execute("UPDATE orders SET discount=100000.00, total=-99860.00 WHERE id=%s", (order_id,))
    cur.execute("RELEASE SAVEPOINT sp5")
    rec("P9", "Drive orders.total negative through an oversized discount",
        "rejected", "*** ACCEPTED ***", "GAP")
except psycopg2.Error as e:
    cur.execute("ROLLBACK TO SAVEPOINT sp5")
    rec("P9", "Drive orders.total negative through an oversized discount",
        "rejected", f"rejected: {str(e).splitlines()[0][:60]}", "OK")

# ------------------------------------------------- P10: DELETE an order_item
cur.execute("SAVEPOINT sp6")
try:
    cur.execute("DELETE FROM order_items WHERE id=%s", (item_id,))
    cur.execute("SELECT count(*) FROM order_audit_log WHERE order_id=%s AND action='delete'", (order_id,))
    n = cur.fetchone()[0]
    cur.execute("ROLLBACK TO SAVEPOINT sp6")
    rec("P10", "DELETE an order_items row (revenue vanishes from the order)",
        "an audit row recording the deletion", f"accepted; {n} 'delete' audit rows written",
        "OK" if n else "GAP")
except psycopg2.Error as e:
    cur.execute("ROLLBACK TO SAVEPOINT sp6")
    rec("P10", "DELETE an order_items row", "audited or refused",
        f"rejected: {str(e).splitlines()[0][:60]}", "OK")

# ---------------------------------------------------------------- report
print("\n" + "=" * 100)
print("ADVERSARIAL PASS ON APPROACH A".center(100))
print("=" * 100)
for pid, attack, expected, observed, verdict in results:
    print(f"\n[{verdict}] {pid}  {attack}")
    print(f"      expected: {expected}")
    print(f"      observed: {observed}")
print("\n" + "=" * 100)
tally = {}
for r in results:
    tally[r[4]] = tally.get(r[4], 0) + 1
print("TALLY:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))

# ---------------------------------------------------------------- cleanup
conn.rollback()
# Deleting the order cascades to order_items and order_audit_log. Since 0004 the
# append-only trigger permits exactly that cascade and refuses a selective
# delete, so the rows must go in this order and not individually.
cur.execute("DELETE FROM orders WHERE id=%s", (order_id,))
cur.execute("DELETE FROM customers WHERE id=%s", (cust_id,))
cur.execute("DELETE FROM product_variants WHERE id=%s", (var_id,))
cur.execute("DELETE FROM products WHERE id=%s", (prod_id,))
cur.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
cur.execute("DELETE FROM categories WHERE id=%s", (parent_cat_id,))
conn.commit()
cur.execute("SELECT count(*) FROM orders")
print("orders after cleanup:", cur.fetchone()[0])
