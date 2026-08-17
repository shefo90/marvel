# Admin Back-Office — Design

**Status:** approved in conversation 2026-08-17, not yet implemented (foundation only).
**Prerequisite reading:** [`2026-08-16-s1-commerce-core-design.md`](2026-08-16-s1-commerce-core-design.md)
(the S1 design, especially §5 money model and §6 URL contract) and
[`2026-08-17-s1-audit-findings.md`](2026-08-17-s1-audit-findings.md) (F5, which this closes).

---

## 1. Why

Today nobody can add a product without a developer. The only path is `scripts/seed.py` — a Python
script run against the database. The role ladder in `services/role_access_level.py` already reserves a
`catalog` role for "products, variants, categories, collections, SEO fields", and nothing uses it,
because no write endpoint exists.

This slice gives the shop operator a back-office: products, variants, images, bilingual content,
pricing, and the offers they decide to run.

**It replaces S1b.** The original S1b was a promotions *rules engine* — rule priority, stacking
resolution, tiered thresholds. The operator decides instead, and the system records what they chose.
That is roughly a quarter of the work and keeps every measurement obligation intact.

---

## 2. Decisions locked

| Area | Decision |
|---|---|
| Sequence | Admin API **and** admin UI, **before** the S2 storefront |
| Serving | `marvel.com/admin`, path-based on the same domain |
| Admin app | Vite + React, client-side only. No SSR, no i18n, no RTL, English-only interface |
| API namespace | `/api/admin/*`, **not** locale-scoped |
| Images | Uploaded to the server, stored on a mounted volume behind a storage interface |
| Bilingual content | Drafts allowed; each language publishes independently |
| Offer types | Sale price, percentage/fixed off a group, BOGO |
| Coupon codes | **Out of scope** |
| Overlapping offers | Best single discount wins; a line never carries two |
| Scheduling | Lives on promotions only — `sale_price` has no date window |
| Deletion | Never hard-delete; archive via status |

### 2.1 Same-origin mitigations

`marvel.com/admin` shares a browser origin with the storefront, which will load GTM, GA4, Meta Pixel
and — per §4 — eventually TikTok and Snap. Any of those can change without us acting. Three
mitigations, all required:

1. The access token is held **in memory only**, never `localStorage` or `sessionStorage`
2. The refresh token is an `HttpOnly; Secure; SameSite=Strict` cookie, unreadable by any script
3. `/admin` is served with its own strict `Content-Security-Policy` forbidding third-party scripts

The admin app is built with a configurable API base URL, so moving to `admin.marvel.com` later is a
proxy config change rather than a code change.

`/admin` must additionally be excluded from the locale router (so it is never read as a locale
segment beside `/en/` and `/ar/`), from `robots.txt`, and from the sitemap.

---

## 3. Access control

Implemented and merged ahead of this spec — `repositories/staff_access.py`, `routes/admin_deps.py`.

The rule follows the precedent `repositories.register.register_staff` set: **the token's
`access_level` claim is never trusted on its own.** It is minted at login and stays valid until the
token expires, so a staff member demoted or deactivated five minutes ago still presents their old
claim. `require_staff` re-reads the actor from the database and re-checks.

| Action | Minimum role |
|---|---|
| Products, variants, images, translations, offers, publish | `catalog` (2) |
| `product_variants.cost` (COGS) | `admin` (4) |

COGS sits behind `admin` because it feeds `contribution_profit` — it is a money field, not a catalog
field.

`require_staff` returns the resolved `User` rather than a boolean, so admin writes can set
`app.actor_user_id`, `app.audit_reason` and `app.audit_source` before mutating money. **This closes
audit finding F5** on the path that matters: staff price corrections become attributable to a named
person instead of falling back to `actor_type='system'`.

---

## 4. Offers

### 4.1 `promotions`

| Column | Notes |
|---|---|
| `id` | |
| `name` | Operator's label, e.g. "Eid 30% off sandals" |
| `type` | `percentage` \| `fixed` \| `bogo` |
| `discount_percent` | numeric(5,2), for `percentage` |
| `discount_amount` | numeric(12,2) EGP, for `fixed` |
| `buy_quantity`, `get_quantity`, `get_discount_percent` | `bogo` only; 100 = free |
| `starts_at`, `ends_at` | timestamptz, nullable = open-ended |
| `is_active` | The operator's on/off switch |
| `created_by_user_id` | FK `users`, `ON DELETE SET NULL` |
| `created_at`, `updated_at` | |

CHECK constraints tie the value columns to the type, so a `percentage` promotion cannot carry a fixed
amount and a `bogo` cannot be saved without quantities.

### 4.2 `promotion_targets`

`promotion_id`, `target_type` (`all` \| `product` \| `variant` \| `category` \| `collection`),
`target_id` (null when `target_type = 'all'`).

**A promotion with no target rows applies to nothing.** Discounting the whole catalog requires
explicitly choosing `all`, so a half-saved offer cannot accidentally mark everything down.

### 4.3 What is deliberately absent

No `promotion_rules`, no `priority` column, no `promotion_redemptions` table. With best-wins
resolution and no coupon codes, redemption counts are a query over `order_items`. Adding a table to
store a derivable number invites it to disagree with the orders it summarises.

### 4.4 Attribution

`cart_items` gains `promotion_id`, `discount_amount`, `discount_source`.
`order_items` gains `promotion_id`, `discount_source` (it already has `discount_amount`).

`discount_source` is `sale_price` | `promotion`.

`orders.promotion_cost_total` — which exists today and is always 0 — becomes the sum of line
discounts where `discount_source = 'promotion'`. Markdowns remain visible as
`unit_list_price − unit_price` without being counted as campaign cost.

This satisfies §3's "coupon/promotion IDs" on the order and §11A's requirement that
`promotion_cost_total` be auditable. Both `discount_amount` and `promotion_cost_total` are already
watched by the migration-0004 money audit trigger, so corrections are recorded automatically.

### 4.5 One pricing implementation

**One function, `repositories/pricing.py`, called by both cart and order creation.**

The worst defect in this project's history (§5 of the handoff) was two customer-identity normalizers
that disagreed, resolving one shopper into two `customers` rows and corrupting every lifetime-value
figure while every individual test passed. Pricing has the identical shape: if the cart prices one
way and checkout another, the shopper sees one number and is charged a different one — which is
exactly the "price mismatch" Merchant Center diagnostics flag.

A parity test asserts the two paths agree, mirroring
`tests/test_catalog_and_identity.py`'s treatment of `services/identity.py`.

### 4.6 Resolution order

Per line:

1. Compute the best **per-unit** price: the lowest of full price, `sale_price`, and each matching
   in-window `percentage`/`fixed` promotion.
2. Evaluate BOGO across matching lines: sort matching units by price descending, group into chunks of
   `buy_quantity + get_quantity`, discount the **cheapest** units in each chunk.
3. Keep whichever of (1) and (2) gave the shopper more. **A line carries one promotion, never two.**

Comparing at line level rather than searching cart-wide combinations is a deliberate simplification.
It is deterministic, never worse than either offer alone, and the operator can explain it to a
customer — which matters more here than optimality.

Only `is_active` promotions whose window contains `now()` are candidates.

### 4.7 Refunds against BOGO

**Refunds are proportional to what was actually paid on the line, never to list price.**

Buy-1-get-1 on two 500 EGP sandals: the shopper pays 500 for two items. Returning one refunds 250,
not 500. Without this rule a shopper buys a BOGO pair, returns one item, and keeps a free product
plus their money — and `net_realized_revenue` goes negative with nothing failing.

`order_items` already carries `refunded_quantity`, `refunded_amount` and a CHECK that
`refunded_amount <= line_total`, so the schema blocks the worst version. This rule makes the
intermediate case explicit.

---

## 5. Product editor

### 5.1 Variant matrix

The operator picks sizes and colours; the system generates the cross product. Price, cost and stock
are set once for the set and overridden per row.

SKUs auto-generate as `{item_group_id}-{SIZE}-{COLOUR}` with a per-row override.
**The UI must state that SKU is immutable after save** — `trg_variants_sku_immutable` enforces it,
because Merchant Center and the Meta catalog key on it. Explaining that at entry is better than
surfacing a `restrict_violation` later.

`UNIQUE(product_id, size, color, material)` already prevents the generator producing duplicates.

`item_group_id` is auto-generated from the slug with an override, not typed from scratch — it is
`UNIQUE` and is Merchant's variant-grouping key.

### 5.2 Constraints are the validation rules

The editor surfaces what the database already enforces rather than duplicating it:

| Constraint | Message |
|---|---|
| `ck_products_active_has_default_variant` | "Add at least one variant before publishing" |
| `ck_product_translations_published_requires_content` | "Arabic needs a title, description and meta description" |
| `ck_variants_sale_price_valid` | "Sale price cannot exceed the price" |
| `ck_variants_sku_format` | "SKU: capitals, digits and hyphens" |
| `ck_variants_size_system` | "Size system needs a size" |

`POST /api/admin/products/{id}/publish?locale=ar` checks preconditions and returns a **structured
list of blockers**, because a raw constraint violation is unreadable. The listing screen shows the
same readiness state per language — that is what makes per-language publishing usable.

### 5.3 Slug changes write redirects

When the slug of an **already published** product changes, the API writes a `url_redirects` row
(301) from the old path. §8A requires it, the table already exists with a `status_code IN (301, 308,
410)` check and a same-locale constraint, and the admin is the only place a rename can originate.
Without this, every rename silently 404s a page Google has indexed.

Arabic slugs default to the Arabic title, slugified against the migration-0003 denylist so real
Arabic text survives. Base slugs are ASCII, per `ck_products_slug_format`.

### 5.4 Products attach to level-2 categories only

`products.category_level` is a generated column pinned to 2, with a composite FK to
`categories(id, level)`. Open question 12 of the S1 design ("may a product attach to a level-1
category?") is therefore already answered **no** in the DDL. The category picker offers level-2
categories only. The S1 design doc should be updated to record this.

### 5.5 No hard deletes

`fk_order_items_product_id` is `ON DELETE RESTRICT`, so anything sold cannot be removed. The editor
archives via status. Deleting a product would orphan the history GA4, Merchant Center and the Meta
catalog key on.

---

## 6. Images

`POST /api/admin/products/{id}/images`, multipart. The server:

1. **Identifies the file by decoding it** — never by extension or declared content type
2. **Rejects SVG** — it is XML that can carry script, and a product photo never needs it
3. Re-encodes to strip EXIF, which carries GPS coordinates from phone cameras
4. Measures `width`/`height` itself. Those columns are `NOT NULL`, and this is precisely why the
   operator should not be typing them
5. Generates thumbnail / card / full derivatives
6. Writes to a content-addressed path on the mounted volume through a thin storage interface
   (`put` / `delete` / `url`), so moving to S3 or R2 later is a config change

Enforced limits: maximum file size, maximum pixel dimensions (a decompression-bomb guard), and an
allow-list of JPEG/PNG/WebP.

`alt_text` is `NOT NULL` with a not-blank CHECK, so **upload requires alt text** — accessibility the
schema already insists on. Per-locale alt text via `product_image_translations`.

Adds Pillow to `requirements.txt`. Adds a named volume to `docker-compose.yml`, which must be
included in any backup procedure — image files are the one piece of state not in Postgres.

"The primary image" is already guaranteed singular — `uq_product_images_primary_product` and
`uq_product_images_primary_variant` are existing partial unique indexes covering the product-level and
variant-level cases. The editor can rely on it; nothing new is needed. `uq_product_images_position`
(`NULLS NOT DISTINCT`) likewise means the reorder UI must renumber positions in one transaction rather
than one row at a time, or it will collide with itself mid-update.

---

## 7. Cache invalidation

Every admin write bumps the public catalog cache version, **with a test asserting the version
changed** — not merely that the code ran.

§5 of the handoff records why: the first cache invalidation in this project was a silent no-op, because
`INCR` on a missing key yields 1 and the default was already 1. It was invisible with Redis down (all
misses) and invisible with Redis up unless the test asserted the value actually moved.
`scripts/check_cache_live.py` is the existing precedent.

---

## 8. Migration 0005

- `promotions`, `promotion_targets`
- `cart_items`: `promotion_id`, `discount_amount`, `discount_source`
- `order_items`: `promotion_id`, `discount_source`

`orders.promotion_cost_total` needs no change — it exists and starts being populated. The primary-image
uniqueness indexes already exist and need no migration.

---

## 8A. Build order

This design is too large for one implementation plan. Four stages, each independently shippable and
each leaving the system working:

| Stage | Contents | Why this order |
|---|---|---|
| **1. Catalog writes** | Create/update products, variants, translations; publish with structured blockers; slug-change redirects; cache bump | Unblocks everything else. The operator can list a product, which is the thing that currently requires a developer |
| **2. Images** | Upload, validation, derivatives, storage interface, volume | Independent of stage 1's data model; products are listable without photos, just not sellable |
| **3. Offers** | `promotions`, `promotion_targets`, `repositories/pricing.py`, attribution, BOGO, refund rule | Needs stage 1 (something to discount). Its migration is the one that is hard to change later, so the data model ships here even though the storefront cannot render offers until S2 |
| **4. Admin UI** | The React app across all of the above | Can begin against stage 1's endpoints and grow; splitting it out keeps backend progress from blocking on frontend decisions |

Stage 3's *pricing* is exercised through the cart API before any storefront exists, so it is
verifiable without S2.

---

## 9. Testing

TDD throughout, per the project's existing discipline.

- **Pricing parity** — cart and checkout produce identical prices and identical attribution for the
  same basket. The `services/identity.py` precedent.
- **Resolution** — best-wins picks the cheapest; a line never carries two promotions; expired and
  inactive promotions are not candidates; a promotion with no targets applies to nothing.
- **BOGO** — the cheapest unit in each chunk is the discounted one; a partial refund returns the
  proportional amount, not list price.
- **Upload security** — SVG rejected; a file whose extension lies about its content is rejected; EXIF
  stripped; dimensions measured rather than trusted.
- **Publish preconditions** — blockers returned as structured data, not a 500.
- **Slug rename** — a 301 `url_redirects` row appears for a published product, and none for a draft.
- **Cache** — the version *changes* after an admin write.
- **Access** — already merged: role gating, deactivation, and the demotion case.

---

## 10. Out of scope

- Coupon codes. `POST /cart/coupon` and `orders.coupon_code` exist and stay dormant.
- Promotion stacking and priority resolution.
- Storefront rendering of offers — that is S2.
- The worker/queue layer, which still blocks S4/S5/S6.

---

## 11. Open questions

1. **Concurrent edits.** Two operators editing the same product will silently overwrite each other.
   `products.updated_at` could carry optimistic locking, but no scheme is designed. Low risk with one
   operator; must be resolved before a second is hired.
2. **F4 from the audit** — `orders.gross_order_value` remains unconstrained. Unchanged by this work.
3. **Admin login URL.** The admin SPA authenticates against the existing locale-scoped
   `/api/en/auth/staff/login`. Reusing it avoids duplicating auth code; the `/en/` segment is
   cosmetically odd in an unlocalized admin. An unlocalized alias is deferred as cosmetic.
4. **Bulk operations.** Nothing here addresses importing a catalog by spreadsheet or bulk price
   changes. Likely wanted once the shop has more than a few dozen products.
