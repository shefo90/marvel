"""Re-probe P6 properly: is order_audit_log actually append-only?

The first attempt tripped ck_order_audit_log_real_change by setting old_value =
new_value, which is an unrelated constraint. A real tamperer keeps them distinct.
"""
import psycopg2

conn = psycopg2.connect(host="localhost", port=5433, user="marvel", password="marvel", dbname="marvel")
cur = conn.cursor()

# minimal fixture
cur.execute("""INSERT INTO categories (parent_id,level,name,slug,list_id,position,is_active,is_indexable,
                                       content_updated_at,created_at,updated_at)
               VALUES (NULL,1,'P6Top','p6-top','p6_top',1,true,true,now(),now(),now()) RETURNING id""")
top = cur.fetchone()[0]
cur.execute("""INSERT INTO categories (parent_id,level,name,slug,list_id,position,is_active,is_indexable,
                                       content_updated_at,created_at,updated_at)
               VALUES (%s,2,'P6','p6-cat','p6_cat',1,true,true,now(),now(),now()) RETURNING id""", (top,))
cat = cur.fetchone()[0]
cur.execute("""INSERT INTO customers (public_id,status,email,orders_count,delivered_orders_count,
                                      lifetime_gross_ordered_revenue,lifetime_delivered_revenue,
                                      lifetime_net_revenue,lifetime_contribution_profit,created_at,updated_at)
               VALUES (gen_random_uuid(),'active','p6@example.com',0,0,0,0,0,0,now(),now()) RETURNING id""")
cust = cur.fetchone()[0]
cur.execute("""INSERT INTO orders (order_number,customer_id,status,locale,currency,subtotal,discount,tax_total,
                                   shipping,total,gross_order_value,payment_status,payment_method,
                                   items_cogs_total,promotion_cost_total,shipping_cost,cod_fee,gateway_fee,
                                   return_cost_total,refunded_amount_total,placed_at,created_at,updated_at)
               VALUES ('P6-PROBE-0001',%s,'pending','en','EGP',100,0,0,20,120,120,'pending','card',
                       0,0,0,0,0,0,0,now(),now(),now()) RETURNING id""", (cust,))
oid = cur.fetchone()[0]
conn.commit()

# generate a genuine audit row
cur.execute("UPDATE orders SET subtotal=200.00, total=220.00 WHERE id=%s", (oid,))
conn.commit()
cur.execute("SELECT id, field, old_amount, new_amount FROM order_audit_log "
            "WHERE order_id=%s ORDER BY id DESC LIMIT 1", (oid,))
aid, field, oldv, newv = cur.fetchone()
print(f"genuine audit row: id={aid} field={field} {oldv} -> {newv}")

print("\n--- P6a: rewrite the recorded amounts, keeping old != new ---")
try:
    cur.execute("UPDATE order_audit_log SET old_amount=1, new_amount=2, old_value='1', new_value='2' "
                "WHERE id=%s", (aid,))
    conn.commit()
    cur.execute("SELECT old_amount, new_amount FROM order_audit_log WHERE id=%s", (aid,))
    print(f"  *** ACCEPTED *** row now reads {cur.fetchone()} — evidence rewritten")
    p6a = "GAP"
except psycopg2.Error as e:
    conn.rollback(); print(f"  rejected: {str(e).splitlines()[0]}"); p6a = "OK"

print("\n--- P6b: delete the audit row outright ---")
try:
    cur.execute("DELETE FROM order_audit_log WHERE id=%s", (aid,))
    conn.commit()
    cur.execute("SELECT count(*) FROM order_audit_log WHERE id=%s", (aid,))
    gone = cur.fetchone()[0] == 0
    print(f"  *** ACCEPTED *** row deleted: {gone} — evidence destroyed")
    p6b = "GAP"
except psycopg2.Error as e:
    conn.rollback(); print(f"  rejected: {str(e).splitlines()[0]}"); p6b = "OK"

print(f"\nP6a (rewrite)={p6a}   P6b (delete)={p6b}")

# cleanup
cur.execute("DELETE FROM order_audit_log WHERE order_id=%s", (oid,))
cur.execute("DELETE FROM orders WHERE id=%s", (oid,))
cur.execute("DELETE FROM customers WHERE id=%s", (cust,))
cur.execute("DELETE FROM categories WHERE id IN (%s,%s)", (cat, top))
conn.commit()
cur.execute("SELECT count(*) FROM orders"); print("orders after cleanup:", cur.fetchone()[0])
