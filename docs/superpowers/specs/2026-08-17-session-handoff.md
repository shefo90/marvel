# Session Handoff — 2026-08-17

For whoever picks this up next. Read this first, then
[`2026-08-16-s1-commerce-core-design.md`](2026-08-16-s1-commerce-core-design.md) (the approved design)
and [`../../../README.md`](../../../README.md) (how to run it, and the invariants that bite).

This document holds what those two do **not**: decisions made in conversation, defects found and fixed,
and why the next steps are ordered the way they are.

---

## 1. What the project is

Egyptian women's footwear and handbag store, modelled on **pixishoes.com** — the user wants the same
functionality *and* the same visual style.

The governing document is `Ecommerce_Tracking_Developer_Requirements (1).pdf` (v1.3, 23 pages). It is not
a website spec — it is a **measurement architecture** spec. Its Definition of Done (§16):

> a test order can be followed end-to-end from original acquisition identifiers through product/cart
> behavior, checkout, payment, shipment, delivered/returned state and realized revenue, with Merchant data
> consistent with the storefront and with no duplicate conversions.

It was decomposed into seven slices (§1.1 of the design doc). **S1 is complete. Nothing else is started.**

---

## 2. State of the code

### Done and verified

- **46 tables**, 3 Alembic migrations, applied and running
- **4 database triggers** — `order_number` + `sku` immutability, and money-column auditing on
  `orders` / `order_items`
- **API**: catalog (bilingual, cached), staff + shopper auth with refresh rotation, server-side cart,
  idempotent order creation
- **46 pytest tests**, all passing (~1.3s with Redis up)
- **224 smoke assertions** across four scripts — weaker evidence, see §6
- **Docker Compose** stack: Postgres (host port **5433**), Redis (6379), API (8000). Verified booting
  clean and serving both locales.

### Not built

| | |
|---|---|
| **Background job queue** | §13 mandates it. Absent from the supplied backend architecture prompt — flagged at the start of the project and still true. **S4, S5 and S6 are all blocked on this.** Redis is already in the stack, so RQ/arq/Celery is additive: proposed `workers/` + `tasks/` top-level dirs following the same layer-first convention. |
| **Admin CRUD** | No way to add a product except `scripts/seed.py`. Tables carry every §8A SEO field; there is simply no endpoint. |
| **Promotions (S1b)** | See §4. Blocks storefront parity. |
| **Frontend** | Nothing at all. |
| **S4 / S5 / S6 / S7** | Not started. |

Rough proportion: **S1 is about a third of the backend.**

---

## 3. Decisions locked (do not relitigate)

| Area | Decision |
|---|---|
| Market | Egypt only, **EGP only**. No multi-currency, no market-scoped pricing |
| Locales | **English + Arabic**. English default and `x-default`. Locale is a **path segment**, never IP or `Accept-Language` |
| Catalog i18n | DB translation rows per locale. UI strings in `locales/en.json` + `ar.json` via react-i18next |
| Arabic slugs | **Real Arabic text**, stored decoded, percent-encoded exactly once at render |
| Catalog model | Every product has ≥1 variant. **The variant is the sellable unit** |
| Identity | `customers` (shoppers, guest or account) separate from `users` (staff) |
| Payments | COD **and** online card |
| Money model | **Approach A** — typed columns + trigger-written audit rows (user chose this over a ledger) |
| VAT | **VAT-inclusive** prices; `orders.tax_total` stays 0 |
| Brand | Single house brand ("Pixi") |
| List attribution | `item_list_id` carried cart → order lines |
| Wishlist | Deferred out of S1 |
| **S2 rendering** | **Option A — React SSR on Vite via Vike.** FastAPI stays a pure JSON API |
| **S2 scope** | **Full pixishoes parity** — functionality and style |

---

## 4. S1b — promotions (blocks S2 parity)

Discovered when scoping the storefront. S1 models `coupon_code` and `sale_price` but **not promotional
rules**. pixishoes runs "Buy 1 Get 1" and "30% OFF", which need:

- a `promotions` table (type, scope, window, priority, stacking rules)
- `promotion_rules` (buy-X-get-Y, percentage off a category/collection, tiered thresholds)
- `promotion_redemptions` (which order used which promotion)
- **per-line discount attribution** on cart and order items

The attribution part is not optional: §3 requires "coupon/promotion IDs" on the order, and §11A requires
`promotion_cost_total` to be auditable. A discount that is just a number nobody can trace back to a rule
fails both.

Build this **before** the storefront's promo UI, or that UI gets rebuilt.

---

## 5. Defects found this session — do not reintroduce

Each was invisible under normal testing. Each now has a guard.

| Defect | Why it hid | Guard |
|---|---|---|
| **Two customer-identity normalizers disagreed** — registration produced `201001234567`, checkout `+201001234567`. Same shopper → two `customers` rows → §11A lifetime values silently wrong | Each layer's own tests passed; only cross-checking two layers revealed it | `services/identity.py` is the single implementation; `tests/test_catalog_and_identity.py` asserts parity over all 7 Egyptian phone forms |
| **First cache invalidation was a no-op** — `INCR` on a missing key yields 1, and the default was already 1 | Invisible with Redis down (all misses); invisible with Redis up unless you assert the version *changed* | `scripts/check_cache_live.py` asserts the bump and the re-read |
| **Slug CHECK rejected all Arabic** — `[[:alnum:]]` is ASCII-only under the column's `COLLATE "C"` | Testing the same regex against a **bound parameter** passes, because parameters carry the DB default collation, not the column's | Migration `0003` uses an ASCII **denylist**; seed data includes Arabic slugs |
| **Deferred FKs emitted twice** — inline in `CREATE TABLE` *and* as `ALTER`, so `carts` referenced `orders` before it existed | Only surfaced on a real `alembic upgrade` | `gen_initial_migration.py` detaches cyclic FKs before rendering |
| **`.dockerignore` excluded `alembic/`** — API container crashed on boot | Only surfaced running compose | Comment in `.dockerignore` explaining why it must stay |
| **Catalog listing N+1** — 2 queries per product | Cache hid it | `scripts/check_query_count.py` enforces a query budget |

---

## 6. Verification honesty

- `tests/` (46 tests) were written **independently** of the implementation. Trust these.
- `scripts/smoke_*.py` (224 assertions) were written **by the agents that wrote the code they test**.
  Useful as regression detection, weak as correctness evidence.
- **Three planned audits never ran** — they died on session limits:
  1. completeness against every field mandated by §2/§3/§4/§11A
  2. the §2 identifier-contract check
  3. an adversarial pass on Approach A

  A missing mandated field is far cheaper to fix now, with no production data, than when S6 discovers it
  via a Merchant feed rejection. **Consider re-running these before building further.**

  > **Update — all three ran on 2026-08-17.** See
  > [`2026-08-17-s1-audit-findings.md`](2026-08-17-s1-audit-findings.md). Both completeness audits pass;
  > the adversarial pass found four defects, four of which are fixed in migration `0004_audit_integrity`.
  > The serious one: `order_audit_log` was freely rewritable and deletable by the application role, which
  > made Approach A's audit trail a convention rather than evidence. It is now append-only. Two items
  > remain open — an unconstrained `gross_order_value`, and money edits that silently record as
  > `actor_type='system'` when `SET LOCAL` is forgotten.

---

## 7. Open questions

Numbered per §8 of the design doc. Nothing is blocked; code uses documented defaults.

**Urgent:**
- **(5) Idempotency retention window** — currently 24h. Must be reconciled against the payment gateway's
  retry horizon *before any gateway goes live*. A window shorter than that horizon lets a late retry slip
  past replay protection and duplicate an order.

**Needed for S2:**
- **Arabic search normalization** — alef/hamza/taa-marbuta folding and diacritic stripping, or Arabic
  search returns wrong results. §5 requires a `search` event, and full parity includes site search.
- **Visual design** — pixishoes style needs an actual design pass: layout, product card, PDP, cart drawer,
  and how the size/colour selector behaves in RTL.
- **Frontend structure reconciliation** — the supplied React structure PDF describes a client-side SPA with
  `.jsx`, `main.jsx`, `AppRoutes.jsx`. Vike replaces the entry points and routing with `+Page`/`+data`
  files. The taxonomy (`components/`, `services/`, `hooks/`, `store/`, `utils/`) survives; the routing
  layer does not.
- **State management** — the PDF suggests Redux Toolkit or Zustand. With SSR and a server-side cart, most
  state is already server-owned, so this is probably much smaller than it looks.

**Lower priority:** (4) derived-column write cadence, (6) cart TTL + merge-collision rule, (7) catalog-side
admin audit, (12) whether a product may attach to a level-1 category, (8)(9)(10)(11)(13) — see design doc.

---

## 8. Recommended next steps, in order

1. ~~**Re-run the three audits** (§6).~~ **Done 2026-08-17** — yielded migration `0004_audit_integrity`,
   exactly the "one short migration" predicted. Findings in
   [`2026-08-17-s1-audit-findings.md`](2026-08-17-s1-audit-findings.md).
2. **Build the worker/queue layer.** Small, and unblocks S4/S5/S6.
3. **S1b — promotions.** Required for storefront parity.
4. **Brainstorm S2 properly**, then spec, then build. §6 of the design doc already fixes the URL contract,
   hreflang, slugs, i18n and the full RTL rule set — S2 *implements* that contract rather than re-deriving
   it. What genuinely needs design is the visual system and component architecture.

Steps 1–3 are backend and independent of each other. If the user wants visible progress sooner, 4 can jump
the queue — but promo UI built before S1b will be rebuilt.

---

## 9. Environment notes

- **Python 3.12**, not 3.14 — `psycopg2-binary` has no 3.14 wheel and building from source needs MSVC.
  `py -3.12` resolves to `F:\python\python.exe`. The venv is at `backend/.venv`.
- **User's own Postgres 17.10** runs on `localhost:5432`, credentials `postgres` / `123`, database
  `postgres`. `backend/.env` currently points there and the S1 schema is applied to it. Compose uses its
  own isolated Postgres on **5433** instead.
- **The test suite needs Redis running** — 1.3s with, 255s without. A slow suite means Redis is down.
- **Workflow/subagent note:** this session hit session limits three times, and a workflow reported
  `domainsBuilt: 0` while the agents had in fact written all their files before dying. **Always inspect the
  working tree before believing a failure report.** Structured returns die before the side effects do.
