# Marvel Commerce

Egyptian women's footwear and handbags store — Egypt only, EGP only, English + Arabic.

Built to the measurement architecture in `Ecommerce_Tracking_Developer_Requirements (1).pdf`, whose
Definition of Done is that a test order can be traced end to end from acquisition identifiers through
cart, checkout, payment, shipment, delivery/return and realized revenue, with no duplicate conversions.

The approved design lives in
[`docs/superpowers/specs/2026-08-16-s1-commerce-core-design.md`](docs/superpowers/specs/2026-08-16-s1-commerce-core-design.md).
Read it before changing the schema — several decisions look arbitrary until you see the requirement
behind them.

## Status

| Slice | State |
|---|---|
| **S1 — commerce core** | Done. 46 tables, 4 migrations, catalog + auth + cart + idempotent orders |
| **Admin stage 1 — catalog writes** | Done. Products, variants, per-language content, publish with structured blockers |
| **Admin stage 2 — images** | Done. Upload, decode-based validation, EXIF stripped, derivatives, content-addressed storage |
| **Admin stage 3 — offers** | Done. `promotions`, one pricing implementation shared by cart and checkout, BOGO, attribution |
| **Admin stage 4 — the UI** | Done. `admin/`, products, images, offers and orders |
| **Order management** | Done. `operations` role: the queue, one order's detail, recorded status moves |
| **S2 — storefront & SEO** | Done. `storefront/`, server-rendered on Vike, bilingual with RTL, sitemaps and JSON-LD. **A shopper can buy** |
| **S3 — browser measurement** | Done. dataLayer, GA4 ecommerce events, Consent Mode v2. Needs a GTM container id |
| **S4 — commerce integrations** | COD works end to end. Background queue done — a Postgres outbox with retries, a dead-letter path and the cart sweeps. **Not done:** payment gateway, courier adapter |
| **S5–S7** | Not started |

394 backend tests, 70 admin tests, 50 storefront tests. Six migrations.

**A shopper can browse in either language, add to a cart, check out with cash on delivery, and an
operator can see the order and move it along.** What is missing is card payment, a courier
integration, server-side measurement, and the catalogue feeds.

## Running it

```bash
docker compose up --build
```

Postgres is published on **5433**, not 5432, so it will not collide with a PostgreSQL already running on
your host. Redis is on the standard 6379 — if you have a standalone Redis container from earlier, remove
it first (`docker rm -f marvel-redis`) or the bind fails.

Migrations run automatically before the API accepts traffic. Then:

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health — reports Postgres and Redis independently

Seed some catalog data:

```bash
docker compose exec api python scripts/seed_taxonomy.py   # the shop's shape
docker compose exec api python scripts/seed.py            # a couple of products
```

`seed_taxonomy.py` creates the category tree, the collections, and the size and
colour values the filter sidebar is built from — with Arabic labels, without which
the Arabic filter sidebar renders "black" and "beige" in Latin script down the side
of an RTL page. Both scripts are idempotent, and everything they create is ordinary
data: renaming a category or removing a colour is a back-office action, not a code
change.

**Back up the `marvel_media` volume.** Uploaded images are the only application state that is not
in Postgres, so a database backup does not cover them. Losing that volume loses every product
photo while the rows that point at them survive.

## Running it without Docker

```bash
cd backend
py -3.12 -m venv .venv                 # 3.12, not 3.14 — psycopg2-binary has no 3.14 wheel yet
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env                 # then fill in DB_URL and SECRET_KEY
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python scripts\seed.py
.venv\Scripts\python -m uvicorn main:app --reload
```

## The background worker

```bash
cd backend
.venv\Scripts\python -m workers.runner        # or: docker compose up -d worker
```

Nothing in the shop *fails* without it — the API never waits on it — but two things quietly stop
happening: idle carts are never marked abandoned, and carts past their TTL are never expired. Once a
payment gateway and a courier exist, this is also what will retry their calls, so it becomes
load-bearing then.

The queue is the `jobs` table, not Redis, even though Redis is in the stack. A job row is written in
the *same transaction* as the change that caused it, so an order and its "capture the payment" job
commit together or not at all; enqueueing to Redis is a second write to a second system, and every
instruction between the two is a window where a crash loses the job with nothing left to show it
existed. `backend/models/jobs.py` has the rest of the reasoning.

A job that succeeds deletes its row, so the table only ever holds work that is outstanding, in
flight, or dead. **The dead-letter queue is therefore a plain query** — this is what to look at when
something is not happening:

```sql
SELECT kind, attempts, last_error, created_at FROM jobs WHERE status = 'dead' ORDER BY created_at DESC;
```

Running two workers is safe: claims use `FOR UPDATE SKIP LOCKED`, and a partial unique index on
`dedupe_key` means the recurring sweeps are scheduled exactly once no matter how many workers try.

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest tests -q
```

**Start Redis first.** The suite runs in ~1.3s with Redis up and ~255s without it — every cache miss
otherwise waits on a refused connection. A slow suite here means Redis is down, not that the tests are slow.

```bash
docker compose up -d redis
```

## Running the admin back-office

Two front ends are planned and they share nothing: `admin/` is a client-side SPA for one logged-in
operator, and the storefront (S2) will be server-rendered, bilingual and RTL. Merging them would put
admin code in the same bundle as the storefront's tracking pixels, which is exactly what the admin's
CSP exists to prevent.

```bash
cd admin
npm install
npm run dev          # http://localhost:5173/admin/
```

The API must be running on 8000. Vite proxies `/api` to it, so the browser sees a single origin —
the same topology as production (`marvel.com` and `marvel.com/admin`), which is why the API needs no
CORS middleware.

**Signing in needs a staff account.** There is no registration screen: `catalog` (2) or above can
reach the back-office, and `admin` (4) is additionally required to set COGS.

```bash
cd backend
.venv\Scripts\python -c "from core.db import SessionLocal; from repositories.register import create_staff_user; db=SessionLocal(); create_staff_user(db, email='you@example.com', password='choose-one', full_name='You', role='admin'); db.close()"
```

**A reload signs you out.** Both tokens are held in memory and nothing is written to storage — the
admin shares an origin with a storefront that will load GTM, GA4 and Meta Pixel, and a refresh token
any script on that origin can read is a fourteen-day admin credential. See §5 of
`docs/superpowers/specs/2026-08-19-admin-ui-design.md`.

```bash
cd admin
npm test             # vitest + testing-library + msw
npm run build
```

## Running the storefront

```bash
cd storefront
npm install
npm run dev          # http://localhost:3000 — redirects to /en
```

The API must be running on 8000; `/api`, `/media`, `/robots.txt` and the sitemaps are proxied to it,
so the browser sees one origin exactly as in production. `npm run dev` and `npm run preview` run the
*same* `server.js`, which is why `/` redirects identically in both.

Two languages, decided only by the URL: `/en/...` and `/ar/...`. `/arabic`, `/AR` and `/ar-eg` are
404s by design — rendering them would be the soft 404 §8A forbids.

```bash
cd storefront
npm test
npm run build
```

## Diagnostic scripts

These are not tests; they answer specific questions about a running system.

| Script | Question it answers |
|---|---|
| `scripts/check_models.py` | Do all 46 models import and every mapper configure? |
| `scripts/check_db.py` | Does `DB_URL` connect, and what server is it? |
| `scripts/verify_triggers.py` | Do the audit and immutability triggers actually fire? |
| `scripts/audit_approach_a.py` | Ten adversarial probes against the money model — what does it actually refuse? |
| `scripts/audit_audit_log_tamper.py` | Can an audit row be rewritten or selectively deleted? |
| `scripts/check_identity_parity.py` | Do registration and checkout normalize a shopper identically? |
| `scripts/check_query_count.py` | Is the catalog listing still O(1) in queries? |
| `scripts/check_cache_live.py` | Does caching, locale isolation and invalidation work with Redis up? |
| `scripts/gen_initial_migration.py` | Regenerates `0001` offline from `Base.metadata` |
| `scripts/seed.py` | Bilingual sample catalog |

`smoke_api.py`, `smoke_auth.py`, `smoke_cart.py` and `smoke_orders.py` are broader end-to-end sweeps
(224 assertions). Note these were written alongside the code they exercise, so they are weaker evidence
than `tests/`, which was written independently.

## Architecture

Flat, layer-first. `main.py` sits at the backend root; every layer is a top-level directory.

```
backend/
├── main.py            FastAPI app + router registration, nothing else
├── core/              db, config, enums — imports nothing from the app
├── models/            SQLAlchemy tables, ONE FILE PER TABLE
├── schema/            Pydantic contracts, one file per domain, zero logic
├── repositories/      all querying, business rules, commits
├── routes/            HTTP layer, one APIRouter per domain, no SQL
├── services/          stateless helpers: tokens, hashing, roles, cache, identity
├── alembic/           migrations
├── scripts/           diagnostics and seed
└── tests/             pytest
```

Imports flow one way: `routes → repositories → models → core`. `services/` imports nothing from the app.

The admin app follows the structure in `React Front-end Project Structure Documentation (1).pdf`,
which is a different convention on purpose — that document is the one the frontend was asked to
match.

```
storefront/
├── server.js          Express + Vike; the same server in dev and production
├── pages/             Vike file-system routing, +Page/+data/+route per screen
├── layouts/           the chrome every page sits inside
├── components/        common/ only — the storefront has no admin-style widgets
├── services/          api, catalog, cart, dataLayer
├── hooks/             locale, cart, page context, tracking
└── utils/             locales, head (the SEO contract), events, money
```

```
admin/src/
├── assets/styles/     SCSS variables and mixins; Ant Design owns colour and type
├── components/        common/ and layout/, each component in its own folder
├── pages/             one folder per route
├── services/          every axios call; no component talks to HTTP directly
├── hooks/             TanStack Query wrappers and shared logic
├── context/           AuthContext — the only client state there is
├── routes/            AppRoutes.jsx and the auth gate
└── utils/             constants mirroring core/enums.py, slugify, jwt decode
```

### Things that will bite you if you don't know them

- **`orders.order_number` and `product_variants.sku` are immutable**, enforced by database triggers. They
  are the identifiers GA4, Google Ads, Merchant Center and the Meta catalog all key on; regenerating one
  silently repoints history.
- **Money columns are audited by a trigger**, not by application code. Any UPDATE to a money column on
  `orders` or `order_items` — and any DELETE of an `order_items` row — writes an `order_audit_log` row
  capturing the old value. Do not write audit rows from Python. To attribute a change to a staff member,
  set `app.actor_user_id`, `app.audit_reason` and `app.audit_source` with `SET LOCAL` in the same
  transaction. Forgetting them is not an error: the row is filed as `actor_type='system'`.
- **`order_audit_log` is append-only.** UPDATE is always refused; DELETE is refused while the parent order
  exists. Deleting an order still cascades its audit rows away — that is the one permitted path. Clean up
  test data by deleting the order, never the audit rows.
- **Customer identity normalization lives only in `services/identity.py`.** Registration and checkout once
  had separate implementations that disagreed on phone format, which resolved one shopper to two customers
  and corrupted every lifetime-value aggregate without anything failing. Do not add a second copy.
- **Cache keys are locale-scoped by construction** — `services/cache.key()` refuses a blank locale.
  Price-bearing payloads use a 60s TTL because a stale cached price is exactly the "price mismatch"
  defect the Merchant diagnostics flag.
- **Slug CHECK constraints are denylists, not allowlists.** `slug` is `COLLATE "C"`, and under the C
  collation POSIX classes like `[[:alnum:]]` are ASCII-only — an allowlist rejects every Arabic slug.
  The failure is invisible when tested against a bound parameter rather than the column.
- **Prices are VAT-inclusive**, so `orders.tax_total` stays 0 and VAT is derived for accounting.
- **Pricing lives in exactly one place**, `repositories/pricing.py`, called by the cart and by
  checkout. A second copy is how the cart shows one number and checkout charges another — which
  had already happened: the order path subtracted the markdown twice and undercharged every
  marked-down order until stage 3 unified the two.
- **A markdown is not a campaign cost.** `unit_list_price - unit_price` is the markdown;
  `discount_amount` is what a promotion took off on top of it, and only that feeds
  `orders.promotion_cost_total`.
- **A promotion with no targets applies to nothing.** Discounting the catalogue means choosing
  `all` explicitly, so a half-saved offer cannot mark everything down.
- **Uploaded images are identified by decoding them**, never by extension or declared content
  type, and SVG is refused outright — it is XML that can carry script.
- **The URL is the only thing that decides language.** Never `Accept-Language`, never a cookie,
  never IP. `<html lang/dir>` is set by the server and never from the browser, and switching
  language is a full navigation (the links carry `rel="external"` so the client router leaves them
  alone).
- **Western digits in both locales.** `ar-EG` defaults to Arabic-Indic, so `Intl.NumberFormat` is
  given `numberingSystem: 'latn'` explicitly. Formatted numerals must never reach analytics —
  dataLayer values carry raw numbers.
- **`item_id` is the SKU** in every measurement event. It is the value GA4, Ads, Merchant Center
  and the Meta catalogue all join on.
- **Deleting an order does not work** while a converted cart points at it:
  `ck_carts_converted_consistency` forbids `status='converted'` with a NULL `converted_order_id`,
  so the FK's `ON DELETE SET NULL` cannot fire. Move the cart out of `converted` first.

## Open questions

Tracked in §8 of the design doc. The urgent one: the idempotency retention window (currently 24h) must be
reconciled against the payment gateway's retry horizon before any gateway goes live — a window shorter
than that horizon lets a late retry slip past replay protection and duplicate an order.
