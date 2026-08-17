# S1 — Commerce Core: Design

**Date:** 2026-08-16
**Slice:** S1 of 7 — Commerce Core
**Source requirements:** `Ecommerce_Tracking_Developer_Requirements (1).pdf` (E-commerce Measurement & Commerce Integration Specification, v1.3, 07 Aug 2026)
**Status:** Draft — awaiting user approval

> **Validation caveat.** The domain models in this document were produced by 12 parallel design agents and
> reconciled by hand. The three planned audit passes (mandated-field completeness, §2 identifier contract,
> and an adversarial pass on Approach A) **did not run** — they failed on a session limit. Collisions
> documented in §3.1 were found by manual reading. This design has not been independently verified against
> the full mandated field list. Re-running those audits is a prerequisite to closing the spec.

---

## 1. Why this slice exists

The source spec is a **measurement architecture** spec, not a website spec. Its Definition of Done (§16) is:

> a test order can be followed end-to-end from original acquisition identifiers through product/cart
> behavior, checkout, payment, shipment, delivered/returned state and realized revenue, with Merchant data
> consistent with the storefront and with no duplicate conversions.

That spans seven independently buildable subsystems. The spec's own §17 lists them as phases. This document
covers **S1 only**.

### 1.1 Full decomposition

| Slice | Contents | Depends on |
|---|---|---|
| **S1 — Data model & commerce core** | Identifier contract (§2), catalog/order/payment/attribution/profit/customer schemas (§3, §4, §11A), auth, idempotent order creation | — |
| **S2 — Storefront & SEO** | React+Vite+TS, crawler-ready rendering, URL/indexability contract, JSON-LD, sitemaps, CWV (§8A). **Rendering strategy: Option A — React SSR on Vite via Vike** (decided 2026-08-17; §1 of the requirements required choosing one before implementation). Rendering stays in React so there is one template language and no server/client markup drift; FastAPI remains a pure JSON API. Cost accepted: a Node process deploys alongside FastAPI. | S1 |
| **S3 — Browser measurement** | dataLayer service, GTM envs, GA4, pixels, Consent Mode v2 (§5, §6, §12) | S2 |
| **S4 — Commerce integrations** | Payment webhooks, courier adapter, background queue, idempotency, retries (§9, §10, §13) | S1 |
| **S5 — Server measurement** | sGTM, Meta CAPI, GA4 MP, Ads offline Delivered + adjustments (§6, §7) | S3, S4 |
| **S6 — Catalogs & BI** | Merchant API v1, catalog adapters, reconciliation, profit dashboards (§8, §11A) | S1, S4 |
| **S7 — QA & handover** | §15 acceptance tests, alert simulation, documentation deliverables | all |

### 1.2 S1 scope boundary

**In scope:** schema + migrations + auth + catalog read API + server-side cart + idempotent order creation.
Ends with a verifiable test order in the database.

**Out of scope:** all webhooks, all courier integration, all tracking destinations, Merchant sync, admin CRUD.

---

## 2. Decisions locked

| Area | Decision |
|---|---|
| **Business** | Egyptian women's footwear + handbags. Reference storefront: pixishoes.com |
| **Market** | Egypt only. **EGP only.** No multi-currency, no multi-market, no market-scoped pricing |
| **Locales** | **English + Arabic.** English is primary and `x-default` |
| **UI strings** | JSON per language — `locales/en.json`, `locales/ar.json` via `react-i18next` |
| **Catalog text** | Localized in the **database** via per-entity translation tables, never in JSON files |
| **Catalog model** | Uniform: every product has ≥1 variant. The **variant is the sellable unit** |
| **Taxonomy** | Two-level categories (Shoes → flats/sandals/heels/sneakers/boots/espadrilles; Bags → handbags/crossbody/clutches/wallets/backpacks) plus cross-cutting **collections** ("Summer Edit", "Pixi Comfort") mapping to §5's `item_list_id` |
| **Identity** | `customers` (shoppers, guest or account) **separate** from `users` (staff role ladder) |
| **Checkout** | Guest checkout **and** optional shopper accounts |
| **Payments** | COD **and** online card gateway, both live |
| **Money model** | **Approach A** — typed columns on `orders`/`order_items`; corrections overwrite and write an audit row |
| **Attribution storage** | Typed indexed columns for the stable §4 core + `JSONB` `extras` for later channel adapters |
| **VAT** | **VAT-inclusive** displayed prices. `tax_total` stays 0; VAT derived for accounting |
| **Brand** | **Single house brand.** `products.brand` is a constant default; no brand table |
| **List attribution** | `item_list_id`/`item_list_name` **carried** from cart through to `order_items` snapshot columns |
| **Wishlist** | **Deferred** out of S1 |
| **Arabic slugs** | **Real Arabic text**, stored decoded, percent-encoded exactly once at render |

### 2.1 Stack (fixed)

- **Frontend:** React + Vite + TypeScript, server-rendered initial HTML (crawler-ready per §1 and §8A)
- **Backend:** FastAPI, Pydantic v2, SQLAlchemy 2.x **synchronous** sessions, PostgreSQL, Alembic
- **Layout:** flat layer-first at repo root (`models/`, `schema/`, `repositories/`, `routes/`, `services/`, `core/`)
- **Conventions:** one file per table in `models/`, `PascalCase` classes, `snake_case` tables/columns/files

### 2.2 Known additions to the supplied backend architecture

The supplied backend architecture prompt has **no worker/queue layer**. §13 mandates one ("Background job
queue for Merchant sync, CAPI, courier/gateway work and retryable webhooks", plus exponential retry and a
dead-letter path). Redis is already in the stack, so this is additive — proposed `workers/` + `tasks/`
top-level directories following the same layer-first convention. **Not built in S1**, but S4 requires it,
and checkout must never block on a third-party call.

---

## 3. Table inventory

61 tables were proposed across the two design runs. Deduplication removed 10 (see §3.1), leaving **51**:
**39 in Tier 1**, 6 in Tier 2, 6 deferred.

### 3.1 Collisions resolved

| Collision | Resolution |
|---|---|
| `orders` / `order_items` proposed twice | Not a real conflict — the payments modeler emitted *partial* tables by design. Merged: `orders` = 35 + 20 money columns; `order_items` = 27 + 7 COGS/refund columns |
| `url_redirects` proposed 4× plus 3 per-entity `*_slug_redirects` | Collapsed to **one** `url_redirects` keyed by `(locale, from_path)`. 7 tables → 1 |
| `customer_acquisition` (33 cols) vs `customer_attributions` (17 cols) | Genuine duplicate; both enforce §11A's "never overwrite first acquisition". Kept the 17-col version (points at a normalized `attribution_touches` row); dropped the 33-col copy |
| `order_audit_log` vs `order_value_audit` | Merged into one `order_audit_log` — the Approach-A keystone |

### 3.2 Tier 1 — exercised by S1's endpoints (39)

| Domain | Tables |
|---|---|
| **Catalog** (6) | `categories`, `products`, `product_variants`, `collections`, `collection_products`, `product_images` |
| **Localization** (7) | `locales`, `product_translations`, `category_translations`, `collection_translations`, `product_image_translations`, `attribute_value_translations`, `url_redirects` |
| **Cart** (3) | `carts`, `cart_items`, `cart_mutations` |
| **Orders** (5) | `orders`, `order_items`, `order_status_history`, `order_audit_log`, `idempotency_keys` |
| **Attribution** (5) | `attribution_visitors`, `attribution_touches`, `cart_attributions`, `customer_attributions`, `order_attributions` |
| **Payments** (4) | `payment_transactions`, `order_payment_events`, `refunds`, `refund_items` |
| **Customers & auth** (7) | `customers`, `customer_identity`, `customer_merge`, `customer_credential`, `customer_refresh_token`, `users`, `refresh_token` |
| **Addresses** (2) | `addresses`, `order_addresses` |

### 3.3 Tier 2 — schema only in S1, wired in S4 (6)

`shipments`, `shipment_status_events`, `courier_providers`, `courier_status_mappings`, `order_returns`,
`order_return_items`.

These carry §3's mandated fulfilment fields (`courier_provider`, `shipment_id`, `tracking_number`,
`shipping_cost`, `delivery_status`, `delivered_at`, `failed_delivery_reason`, `return_reason`,
`returned_at`). Landing them in the same migration set keeps the schema coherent; nothing writes to them
in S1.

`shipment_status_events` must model §10's normalized status set exactly: `shipment_created`,
`ready_for_pickup`, `picked_up`, `in_transit`, `out_for_delivery`, `delivered`, `delivery_failed`,
`postponed`, `return_initiated`, `returned`, `return_received`, `cancelled`, `cod_collected`,
`cod_remitted`.

### 3.4 Deferred entirely (6)

| Table | Owner slice |
|---|---|
| `payment_webhook_events`, `courier_webhook_events` | S4 |
| `catalog_channel_syncs`, `marketing_spend_daily` | S6 |
| `seo_urls`, `facet_landing_pages` | S2 |

---

## 4. The identifier contract, made concrete

§2 is titled "Non-negotiable identifier contract" and warns that *"tracking accuracy will collapse if
different systems use different product/order identifiers."*

| §2 identifier | Column | Enforcement |
|---|---|---|
| `product_id` | `products.id` | Surrogate PK. Never derived from title or slug |
| `variant_id` / SKU | `product_variants.sku` | The sellable unit. One row = one SKU = one Merchant `offer_id` = one GA4/Ads `item_id` = one Meta/TikTok/Snap `content_id` = one `order_items` line target |
| `item_id` | **same column** | No translation layer exists, so it cannot drift |
| `order_id` | `orders.order_number` | Human-readable external ref (`ORD-100245`), unique, generated once |
| `transaction_id` | **same column** | §2's "never regenerate on refresh" |
| `customer_id` | `customers.id` | Internal, non-PII, never exposed to the browser |
| `event_id` | *not S1* | Derived from `order_number` in S3/S5 |

**Locale never touches any identifier.** Arabic slugs live in `product_translations.slug`; identity stays
on the base row. A localized slug becoming an identifier would silently poison every catalog adapter in S6.

**Recommended hardening:** a `BEFORE UPDATE` trigger on `orders.order_number` that raises on change. It
costs nothing and makes §2's "never regenerate" unfalsifiable rather than merely documented.

---

## 5. Money model (Approach A)

### 5.1 Columns

**`orders`:** `gross_order_value`, `subtotal`, `discount`, `tax_total`, `shipping`, `total`,
`items_cogs_total`, `promotion_cost_total`, `shipping_cost`, `cod_fee`, `gateway_fee`, `return_cost_total`,
`refunded_amount_total`, `last_refunded_at`, `business_date`.

**COD set:** `cod_amount`, `cod_collection_status`, `cod_collected_at`, `cod_remitted_amount`,
`cod_remitted_at`.

**Payment set:** `payment_status`, `payment_method`, `payment_provider`, `gateway_transaction_id`,
`payment_initiated_at`, `paid_at`, `payment_failure_reason_category`, `purchase_confirmed_at`.

**`order_items`:** `unit_cogs`, `line_cogs`, `cogs_snapshot_source`, `line_discount_amount`,
`refunded_quantity`, `refunded_amount`, `restocked_quantity`, plus the catalog snapshot (`sku`,
`item_group_id`, `product_title`, `variant_label`, `variant_attributes`, `brand`, `category_path`,
`product_url`, `unit_list_price`, `unit_price`) and the list-attribution snapshot (`item_list_id`,
`item_list_name`).

### 5.2 Discipline rules — the price of Approach A

These are mandatory. Approach A is only auditable if all four hold.

1. **Every money-column mutation writes an `order_audit_log` row, enforced by a Postgres trigger — not by
   application code.** Application-level auditing means one repository function that forgets it silently
   destroys §11A's audit chain with nothing failing loudly.
2. **`net_realized_revenue` and `contribution_profit` are stored but derived.** A nightly reconciliation job
   must recompute them independently and alert on divergence (§13 requires scheduled reconciliation).
3. **The audit log's `old_value` supplies §6's Google Ads RETRACTION/RESTATEMENT.** Those adjustments need
   the *original* conversion value alongside the corrected one. Under a ledger this is free; under Approach A
   it exists only because the audit row captured it. **This is where Approach A is most likely to bite.**
4. **COGS is snapshotted at order creation and never recalculated** — §11A's explicit "do not recalculate
   old orders from today's product cost."

### 5.3 §11 funnel — computable from these columns

| Metric | Derivation |
|---|---|
| Orders | count of accepted orders |
| Shipped | orders with a shipment handed to courier |
| Delivered | orders whose shipment reached `delivered` |
| Delivery rate | Delivered ÷ Shipped (denominator labelled explicitly) |
| Gross ordered revenue | Σ `gross_order_value` at creation |
| Delivered revenue | Σ `total` where delivered |
| Net realized revenue | Delivered revenue − refunds/returns − defined cost adjustments |
| Contribution profit | Net realized revenue − COGS − attributable fulfilment/payment/return costs |
| CAC per delivered order | ad spend ÷ delivered orders (spend arrives in S6) |

---

## 6. Localization contract

> **What lands in S1:** §6.1 (translation tables, `locales`, `url_redirects`) and §6.4's slug
> normalization rules — these are schema and are built now.
>
> **What is contract-only:** §6.2, §6.3, §6.5, §6.6 and §6.7 describe behaviour **S2 implements**. They are
> recorded here because they constrain the S1 schema — in particular the `seo_urls` table they reference is
> deferred to S2 (§3.4), so the sitemap `CHECK` constraint in §6.5 ships with that table, not with the S1
> migrations.

### 6.1 Schema

- **One translation table per translatable entity** — not a polymorphic table. Shared columns via an
  abstract SQLAlchemy declarative mixin using `declared_attr`; each concrete table still lives in its own
  file with a `PascalCase` class.
- **`locales` reference table** (`code` PK `'en'|'ar'`, `hreflang`, `is_default`, `text_direction`,
  `is_active`, `sort_order`). Every translation table's `locale` column FKs to it. **Not** a native
  Postgres ENUM.
- **Slug uniqueness is `(locale, slug)`**, not global.
- **Redirect history is locale-scoped.** `url_redirects` keyed on `(locale, from_path)`; redirects are
  always 301 and always within the same locale prefix. Chains collapse at write time so no request resolves
  through more than one hop.
- **Non-translatable fields stay on the base row:** price, SKU, stock, GTIN, brand, weight (§8's
  single-source-of-truth rule).

### 6.2 Fallback and hreflang

- **Cluster membership derives from published translation rows only.** Locale L is a member iff a
  translation row exists for `(entity, L)` with `status='published'` and non-empty title, slug and
  description. Draft and machine-stub rows are never members.
- **A cluster of size 1 emits no hreflang at all** — not even self-reference. Emitting `hreflang="ar"`
  pointing at a URL with no Arabic content is a documented error.
- **Non-contradiction invariant, asserted at render time and in CI:** for every indexable page,
  `canonical == alternates[current_locale]` AND `canonical ∈ set(alternates.values())`. A page failing this
  must 500 in dev/CI, and log+alert+self-canonical in production.
- **When an Arabic translation is first published** after `/ar/` was served under the English slug via
  fallback, insert a redirect row `(locale='ar', old_slug=<english slug>)`. The fallback URL was a real URL
  and will have been linked and shared.

### 6.3 URL contract

- **Locale-prefixed paths:** `/en/...`, `/ar/...`. English is `x-default`.
- **Root `/` returns 302 (never 301) to `/en`** for all agents. No IP-based and no `Accept-Language`
  redirect anywhere — §8A's "avoid forcing every crawler to another version", applied to language.
  `/` appears in no sitemap; `x-default` points at `/en`, not `/`.
- **Unknown/malformed locale segments** (`/ar-eg/`, `/AR/`, `/arabic/`) return 404 unless in an explicit
  alias map, in which case they 301. Locale-less legacy paths 301 to `/en/...`. Neither may render at 200.
- **Variant URLs are `?variant={sku}`** on the same-locale product path — never `#` fragments (§8A forbids
  fragments as variant identity). They canonical to the clean parent product URL, carry no hreflang, and are
  never in a sitemap.
- **Pagination:** page 2+ self-canonicals to itself, never to page 1. Stays crawlable via real `<a href>`,
  excluded from sitemaps, and emits hreflang for page N only when that page genuinely exists in the other
  locale.

### 6.4 Arabic slugs

**Decision: real Arabic text**, stored decoded (real Unicode) in the DB, percent-encoded **exactly once** at
render.

Every surface — `<a href>`, canonical, hreflang, sitemap `<loc>`, the 301 `Location` header and the Merchant
feed `link` — must be byte-identical: NFC-normalized, uppercase hex. Encoding drift between surfaces makes
Google see two distinct URLs and hreflang reciprocity silently fails with "no return tags".

**Normalization rules, pinned once and versioned:** NFC; strip harakat (U+064B–U+0652) and tatweel (U+0640);
spaces → `-`; no ZWNJ/ZWJ; no trailing punctuation. If these rules change later, every stored slug shifts
and every old URL needs a 301 — so the normalizer carries a version.

**Known hazard:** invisible bidi and joiner characters — LRM/RLM (U+200E/U+200F), embedding/override
(U+202A–U+202E), isolates (U+2066–U+2069), ZWJ/ZWNJ (U+200C/U+200D), tatweel — survive copy-paste from Word
and Photoshop. Two visually identical slugs become two distinct rows and a duplicate-content pair that the
`(locale, slug)` unique index will happily accept. Slug input must be sanitized against this set.

### 6.5 Sitemaps

**Membership is a DB invariant, not application logic:**

```
CHECK (in_sitemap = false OR (is_indexable = true AND http_status = 200 AND canonical_url = absolute_url))
```

It is therefore structurally impossible to emit a noindex, redirecting, cross-canonicalled or 404 URL into
a sitemap. Generation is a plain `SELECT ... WHERE in_sitemap AND sitemap_group = ? AND locale = ?`.

**`lastmod` per (entity, locale):** `GREATEST(products.seo_content_updated_at, primary_image.updated_at,
product_translations.updated_at WHERE locale = this locale, cluster.cluster_version_at)`. The other locale's
timestamp is deliberately excluded — editing only the Arabic description must move `/ar/` lastmod and leave
`/en/` untouched. `lastmod` can never be read from `products.updated_at` alone.

Sitemaps are referenced from `robots.txt` and submitted once in Search Console. **No sitemap ping job** —
that endpoint is retired.

### 6.6 JSON string files

- `locales/en.json` + `locales/ar.json`, one physical file per language, namespaced via top-level objects
  within each file.
- **Arabic has six CLDR plural categories** (`zero`, `one`, `two`, `few`, `many`, `other`) against English's
  two. i18next v21+ uses `Intl.PluralRules`; key suffixes must cover all six for Arabic.
- **Western (ASCII) digits in both locales** for prices, sale prices, EU sizes, quantities, percentages,
  order IDs, SKUs and tracking numbers. `Intl.NumberFormat` must force the Latin numbering system explicitly
  (`ar-EG-u-nu-latn` or `{ numberingSystem: 'latn' }`) — `ar-EG` defaults to Arabic-Indic digits.
- **Formatted numerals must never reach analytics.** dataLayer `value`, API bodies and event payloads carry
  raw numbers (§5).
- **Never in these files:** product names, category names, anything from the DB, anything PII.
- **The JSON files may not be the source of any indexable page's title, description, canonical or hreflang.**
  Those come from the DB via the server render.
- **TypeScript:** translation keys must be type-derived from the JSON so a missing or renamed key is a
  compile error.
- **Loading:** the correct locale's strings must be in the **first** HTML response, not fetched after
  hydration (§8A + §15's hydration test).

### 6.7 RTL contract (implemented in S2)

- `<html lang="ar" dir="rtl">` resolved **server-side from the URL locale prefix only** — never from
  `Accept-Language`, a cookie, or IP. Present in the initial HTML.
- `dir`/`lang` owned by the server document template, not React. Ban client-side
  `document.documentElement.dir = …` and enforce with a CI lint over the built bundle.
- **One stylesheet serves both directions.** No compiled `rtl.css` twin.
- Use CSS logical properties (`margin-inline-*`, `padding-inline`, `inset-inline`, `text-align: start`,
  `border-inline`). Do **not** convert `width`/`height` to `inline-size`/`block-size` — both locales are
  `horizontal-tb`, so that mapping is a no-op.
- **Stays physical:** `box-shadow`/`text-shadow`/`drop-shadow` offsets, `transform`, horizontal keyframes,
  `background-position` keywords, gradient direction, `clip-path`, `object-position`. Maintain a short
  explicit allowlist of exceptions needing a manual flip.
- Directional transforms use one custom property: `:root { --dir: 1 }` / `[dir="rtl"] { --dir: -1 }`, then
  `translateX(calc(var(--dir) * 100%))`.
- **Never** `flex-direction: row-reverse`, `order:`, or reversed DOM to achieve RTL. DOM stays in reading
  order; reversal comes from `direction` alone.
- Carousels must not do raw `scrollLeft` arithmetic — use direction-aware `scrollBy`/`scrollIntoView`.
- **Isolate LTR-by-nature strings** inside Arabic text with `<bdi>` or a `.dir-ltr` utility: order IDs, SKUs,
  tracking numbers, phones, emails, URLs, Latin brand names, prices with adjacent punctuation.
- **Fonts:** one dual-script family (recommended IBM Plex Sans Arabic; alternatives Cairo, Tajawal), two
  weights max (400/700), self-hosted WOFF2 same-origin, hashed + immutable cache, `@font-face` in the
  inlined critical CSS. `font-display: swap` (not `optional`, not `block`). `font-synthesis: none` and a real
  700 weight — synthesized bold degrades Arabic joins. Subset by unicode-range block only; never strip
  GSUB/GPOS/ccmp or the init/medi/fina/isol/rlig/mark/mkmk features.
- **One font preload per route**, chosen server-side by locale, with `crossorigin` (mandatory even
  same-origin). If the route's LCP element is an image, its preload comes **before** the font preload.
- Keep `font-size` identical across locales; express the Arabic difference as a locale-scoped line-height
  token (`[lang="ar"] { --line-height-body: 1.75 }` vs `1.5`).
- **No component may be sized from its English string.** Review every text-bearing component at 130% string
  length and the AR line-height token.
- **Locale switching is a full navigation**, never an in-page re-render or runtime RTL transform pass.
- §8A's CWV gates (LCP ≤ 2.5 s, INP < 200 ms, CLS < 0.1 at p75) apply to **each locale independently**. RUM
  must carry a locale dimension and alert on AR-only divergence, not just the blended p75.

---

## 7. S1 acceptance criteria

S1 is done when:

1. All Tier 1 + Tier 2 tables exist via reviewed Alembic revisions; no table is created ad hoc from
   application code.
2. `GET /products` and `GET /products/{slug}` return catalog data in both locales, resolving slugs through
   `(locale, slug)` and honouring the fallback policy.
3. `POST /cart` and `PATCH /cart` maintain a server-side cart that survives browser loss and carries the
   §4 attribution snapshot.
4. `POST /orders` is idempotent — a replayed request with the same idempotency key returns the original
   order and creates nothing new.
5. A test order exists in the database with: an immutable `order_number`, a complete attribution snapshot
   copied from the cart, per-item COGS snapshots, and a resolved `customers` row.
6. Mutating any money column on that order writes an `order_audit_log` row **via the trigger**, with
   `old_value` populated.
7. `attribution_touches` shows first-touch preserved after a simulated second visit through a different
   campaign.
8. Staff auth issues access + refresh tokens with rotation; the role ladder gates a protected endpoint.

---

## 8. Open questions

Items flagged by the design agents that still need a decision. None block starting implementation; all
should be closed before the relevant code lands.

| # | Question | Blocking |
|---|---|---|
| 1 | **Shipping address snapshot placement** — `orders.shipping_address_snapshot` (recommended: order-owned and immutable, since the address is part of what was agreed at checkout) vs on the shipment row. §3 never names it explicitly | S1 order creation |
| 2 | **Card auth/capture split** — §9 lists only `payment_initiated`/`succeeded`/`failed`. If the chosen Egyptian gateway separates authorization from capture, add `authorized`/`captured` to the enum before go-live rather than overloading `initiated` | S4 |
| 3 | **COD remittance granularity** — couriers remit in *batches* covering many orders. The per-order columns may need a `cod_remittance_batches` entity in S4, with order columns populated from batch allocation | S4 |
| 4 | **`net_realized_revenue` / `contribution_profit` write cadence** — nightly reconciliation job (assumed) vs synchronous on each cost event | S1 |
| 5 | **Idempotency key retention window** — defaulted to 24h. Must be confirmed against the gateway's retry horizon (a shorter window lets a late retry bypass replay protection) and against §12's PDPL retention rules | S1 |
| 6 | **Cart TTL and merge-collision rule** — suggested guest 30d sliding, customer-linked 90d, abandoned at 24h inactivity; on variant collision, sum quantities. §11A requires the rule be explicit and documented | S1 |
| 7 | **Catalog-side admin audit** — §13 requires an audit trail for manual changes. Only `url_redirects.created_by_user_id` is wired. Do catalog price/cost/stock edits need audit rows? If so that is a separate catalog-side audit table, decided now rather than retrofitted | S1 |
| 8 | **Variant URL indexability** — currently variants canonical to the product page and carry no SEO fields. §8 asks for "stable variant URLs/identifiers" but does not settle indexability | S2 |
| 9 | **`sale_price_effective_date`** — Merchant supports a start/end window. Modeled as a plain nullable `sale_price`. If promotions are *scheduled* rather than manually toggled, two timestamp columns are needed before the first campaign | S6 |
| 10 | **Faceted-navigation allowlist** (§8A) — needs its own table mapping approved facet combinations to slug + SEO fields + canonical policy. Assigned to S2 | S2 |
| 11 | **`size_system` on variants** — included because Merchant rejects footwear offers with ambiguous sizing. Confirm the value set (EU expected for EG) | S6 |
| 12 | **Product-to-category rigidity** — a composite FK requires products to attach to *level-2* categories. Confirm no product ever needs to sit directly on "Shoes" or "Bags" | S1 |
| 13 | **`tags` as Postgres ARRAY** — fine unless tag-based SEO landing pages are planned, in which case tags must become a table with slug + SEO fields *before* launch | S2 |

---

## 9. Next steps

1. Close open questions 1, 4, 5, 6, 7 and 12 (the S1-blocking ones).
2. **Re-run the three audit passes** that failed — completeness against the mandated field lists,
   §2 identifier contract, and the Approach-A adversarial pass.
3. Produce the implementation plan (writing-plans skill).
