# S1 Audit Findings — 2026-08-17

The three audits [`2026-08-17-session-handoff.md`](2026-08-17-session-handoff.md) §6 recorded as never
having run. All three ran against the **live compose database** (Postgres on 5433), not against the model
files, so every result below is what the schema actually enforces rather than what it appears to declare.

**Verdict: the two completeness audits pass. The adversarial pass found four defects, one of them serious.**

Probe scripts are in the session scratchpad; each ran inside a transaction and cleaned up after itself
(`orders` count was 0 before and 0 after).

---

## Audit 1 — Completeness against §2 / §3 / §4 / §11A — **PASS**

Every field those sections mandate is either present or traceable to a deferral the design doc already
records. Nothing is missing by accident.

| Section | Result |
|---|---|
| **§3 product/variant** (23 mandated fields) | All present. "Feed sync timestamps" lives in `catalog_channel_syncs` — deferred to S6 by design §3.4, not an oversight |
| **§3 order/fulfilment** (28 mandated fields) | All present except **promotion IDs** — the known S1b gap. `orders.coupon_code` stores a code string, not a traceable rule ID |
| **§4 attribution** (7 groups) | UTM, Google, Meta, GA, partner and context fields all typed. TikTok (`ttclid`/`_ttp`) and Snap (`sc_click_id`/`sc_cookie1`) are not typed columns — see note below |
| **§11A profit/LTV/BI** | All cost, revenue-stage and customer-value fields present. Ad spend lives in `marketing_spend_daily` — deferred to S6 by design §3.4 |

**On TikTok/Snap:** §4 qualifies both with "where the channel is enabled and permitted", and requires that
"new channel adapters must extend the same order snapshot rather than inventing a separate source of
truth." `attribution_touches.extras` and `order_attributions.extras` (both `jsonb NOT NULL`) satisfy that.
This is a design choice, not a gap — but the rule is currently unwritten. **Write it down**, or the first
TikTok adapter will add a fifth attribution table.

---

## Audit 2 — §2 identifier contract — **PASS**

All seven identifiers are not merely documented but enforced in the database.

| §2 identifier | Enforcement verified |
|---|---|
| `product_id` | `products.id` bigint PK; slug is `UNIQUE` but never load-bearing as an ID |
| `variant_id` / SKU | `UNIQUE(sku)` **+ `trg_variants_sku_immutable`** — UPDATE rejected live |
| `item_id` | Same `sku` value carried onto `cart_items.sku` and `order_items.sku` |
| `order_id` | `UNIQUE(order_number)` **+ `trg_orders_order_number_immutable`** — UPDATE rejected live |
| `transaction_id` | Is `order_number`; the immutability trigger makes "never regenerate" unfalsifiable |
| `event_id` | `logical_event_id` is `UNIQUE` on **all six** carrier tables — `cart_mutations`, `order_payment_events`, `order_status_history`, `order_returns`, `refunds`, `shipment_status_events` |
| `customer_id` | `customers.public_id` UUID, non-PII, and `orders.customer_id` is nullable for guests |

Webhook replay is additionally guarded by `UNIQUE(provider, provider_event_id)` on `order_payment_events`
and `UNIQUE(provider_id, provider_event_id)` on `shipment_status_events` — both webhook receivers.

The DoD's "no duplicate conversions" rests on this layer, and this layer holds.

---

## Audit 3 — Adversarial pass on Approach A — **4 defects**

Ten probes attacked the money model. Six were repelled: identifier immutability (both triggers fire), the
`total = subtotal − discount + tax + shipping` identity, the non-negative guards, and audit rows for every
watched column. Four got through.

### F1 — `order_audit_log` is not append-only *(serious)*

A row was rewritten and then deleted outright, both accepted, using the same `marvel` role the API connects
as:

```
genuine audit row: id=6 field=total 120.00 -> 220.00
P6a rewrite → ACCEPTED, row now reads (1.00, 2.00)   — evidence rewritten
P6b delete  → ACCEPTED, row gone: True               — evidence destroyed
```

Design §5.2 rule 3 already identifies why this matters: *"The audit log's `old_value` supplies §6's Google
Ads RETRACTION/RESTATEMENT... This is where Approach A is most likely to bite."* Under a ledger the original
conversion value is structural; under Approach A it exists **only** in this table. A table the application
role can silently rewrite is a convention, not an audit trail, and §11A requires corrections be *auditable*.

An initial probe appeared to pass here — it set `old_value = new_value`, which trips the unrelated
`ck_order_audit_log_real_change`. Retested with distinct values, both attacks succeed.

**Fix:** `BEFORE UPDATE OR DELETE` trigger on `order_audit_log` that always raises. Cheap, and turns
tampering into an act loud enough to require dropping a trigger.

### F2 — `unit_list_price` mutations are unaudited

`trg_order_items_money_audit` watches eight columns. `order_items` has **nine** numeric columns — the
omitted one is `unit_list_price`, written at order creation from `variant.price`
([repositories/order.py:461](../../../backend/repositories/order.py#L461)).

```
P1  UPDATE order_items.unit_list_price 150 -> 999  →  0 audit rows written
P2  UPDATE order_items.line_total      100 -> 555  →  1 audit row written
```

This directly violates design §5.2 rule 1: *"**Every** money-column mutation writes an `order_audit_log`
row."* `unit_list_price` is the pre-discount reference price — it's what per-line discount attribution and
GA4's `price`/`discount` split are computed against.

**Fix:** add `'unit_list_price'` to the trigger's argument list.

### F3 — DELETE writes no audit row

Both money triggers are `AFTER UPDATE` only.

```
P10  DELETE FROM order_items  →  accepted; 0 'delete' audit rows written
```

An entire revenue line can leave an order with no trace. `order_audit_log.action` already has an
`'update'` value implying others were intended.

**Fix:** extend both money triggers to `AFTER UPDATE OR DELETE`, writing `action='delete'` with the `OLD`
amounts.

### F4 — `gross_order_value` is unconstrained

```
P7  UPDATE orders SET gross_order_value = 999999.00  →  accepted (total was 140.00)
```

Per §5.3 this column is the Σ behind "Gross ordered revenue" and is defined as the value **at creation**.
Note it *should* diverge from `total` after later corrections, so a `= total` constraint would be wrong.
The correct guard is immutability after insert, matching `order_number` — but that forecloses legitimate
same-day restatement, so it is a judgment call rather than an obvious fix.

### F5 — residual risk: unattributed money edits

```
P3  UPDATE orders SET total=140 with no SET LOCAL app.actor_user_id
    → recorded as actor_type='system', actor_user_id=None, source='db_trigger'
```

Forgetting the `SET LOCAL` convention doesn't fail — it silently files a staff edit as a system one. A
trigger can't distinguish the two. Mitigate with a repository helper that sets the GUCs, plus the §13
reconciliation job alerting on `actor_type='system'` rows outside known automated flows. Not a schema
defect; recording it so it isn't rediscovered.

---

## Bonus finding — three pseudo-boolean columns

Found while dumping the schema; outside the three audits' scope.

Of 24 `is_*` columns, 21 are `boolean`. Three are `character varying` holding `'Y'`/`'N'`:

| Column | CHECK constraint |
|---|---|
| `shipments.is_active` | `IN ('Y','N')` |
| `shipment_status_events.is_unmapped` | `IN ('Y','N')` |
| `order_audit_log.is_monetary` | **none — accepts any string** |

`WHERE is_active` is a type error against a varchar, so every query needs `= 'Y'`, and `is_monetary` has no
constraint at all. With no production data this is a free fix; after S6 it is a data migration.

---

## Recommended migration 0004

| Fix | Risk |
|---|---|
| F1 — append-only trigger on `order_audit_log` | None. Nothing legitimately updates audit rows |
| F2 — add `unit_list_price` to the money trigger | None |
| F3 — extend money triggers to `OR DELETE` | None |
| F6 — convert three varchar flags to `boolean` | Low; needs a `USING (col = 'Y')` cast and model + repository updates |
| F4 — freeze `gross_order_value` after insert | **Judgment call** — blocks same-day restatement |

F1–F3 and F6 are mechanical. F4 needs a decision first.
