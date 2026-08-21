# Session Handoff — 2026-08-21

**Start here.** Then [`../../../README.md`](../../../README.md). Everything before this document is
superseded — including [`2026-08-19-session-handoff.md`](2026-08-19-session-handoff.md), whose three
"do these first" items are all now closed.

---

## 1. The first ten minutes

```bash
docker compose up -d redis        # or the test suite takes 255s instead of 20s

cd backend
.venv\Scripts\python -m pytest -q                # expect 394 passed
.venv\Scripts\python -m uvicorn main:app --port 8000
.venv\Scripts\python -m workers.runner           # optional; see §9

cd ../storefront && npm run dev   # http://localhost:3000
cd ../admin      && npm run dev   # http://localhost:5173/admin/
```

**A staff account already exists:**

```
admin@marvelshop.com  /  Marvel-Admin-2026!      role: admin (level 4)
```

`.local` domains are rejected by the login endpoint's email validation, so a new account needs a
real-looking domain — the first attempt at this created an account that could never sign in.

**Python 3.12, not 3.14** — `psycopg2-binary` has no 3.14 wheel. Venv at `backend/.venv`. Tests run
against the user's own Postgres on **5432** (`postgres`/`123`/`postgres`, from the gitignored
`backend/.env`); compose has its own on 5433. **A git worktree will not work** — `.env` is
gitignored, so a fresh worktree cannot run a single test. Use a branch.

---

## 2. Read this before debugging the running app

**Check what is actually bound to port 8000.**

Most of one session was spent on a storefront that looked broken — two products, dead
`cdn.example.com` image URLs, missing fields the API demonstrably returned. None of it was a bug. A
`marvel-api` **Docker container** was holding port 8000, running a stale baked image against the
**compose database on 5433**, while every seed in that session had written to the **host Postgres on
5432**. It was a different application talking to a different database.

```bash
docker ps                 # is marvel-api up?
docker stop marvel-api    # if you are running the host uvicorn
```

`docker compose up` and a host uvicorn fight over 8000 every time. Pick one.

**A change to a cached payload's *shape* needs an invalidation, not just a restart.** Adding a field
to a cached dict and restarting the API still serves the old shape, because Redis holds payloads
built by the old code. This cost real time twice:

```bash
.venv\Scripts\python -c "from repositories.taxonomy import invalidate_taxonomy; invalidate_taxonomy()"
```

---

## 3. Where things stand

| | |
|---|---|
| **Branch** | `admin-ui` (59 commits ahead of `main`), stacked on `admin-catalog-writes` (17). Both pushed |
| **`main`** | `681779c` — has none of it |
| **Tests** | **394 backend**, **70 admin**, **50 storefront**. All green |
| **Migrations** | `0001`–`0006` on the local DB. **Compose (5433) is behind** — `docker compose up -d --build api` picks new code up; a plain `restart` does not, because the image bakes it in |

| Slice | State |
|---|---|
| S1 commerce core | Done |
| Admin stages 1–4 (catalog, images, offers, UI) | Done |
| Order management | Done |
| Cart lifecycle | Done — carts are marked abandoned and expired |
| **Catalog browse** | **Done** — category/collection pages, facets, sorting, admin CRUD, seeded taxonomy |
| S2 storefront & SEO | Done — SSR on Vike, bilingual, RTL, sitemaps incl. categories, JSON-LD, hreflang |
| S3 browser measurement | Done — dataLayer, GA4 ecommerce events, Consent Mode v2 |
| S4 commerce integrations | Background queue done. **Payment and courier are the user's own work** |
| S5 server measurement | Not started |
| S6 catalogs & BI | Not started |
| S7 QA & handover | Not started |

**The user has explicitly taken payment and shipping off this project's plate.** Do not build them;
leave clean seams.

---

## 4. What to do next

**In order. None of these needs anything from the user.**

1. **Admin screens for categories and collections.** The API is complete
   (`/api/admin/taxonomy/...`, `repositories/admin_taxonomy.py`) and there is **no UI at all**, so
   the operator manages the taxonomy the shop is built around by hand-written HTTP. This is the last
   piece of the browse slice and the most valuable thing left.
2. **Bump `catalog_updated_at` / `inventory_updated_at` / `content_updated_at` on write.** Confirmed
   still zero writers. **Blocks S6** — the incremental feed silently skips every edited variant.
3. **Search.** Blocked on the Arabic normalization decision in §10, but the English half and the
   `search` event §5 requires are not.
4. **Shopper accounts** — register, login, order history, addresses. Tables exist and are unused.
5. **S6 feeds**, then **S5 server measurement**, then **S7**.

---

## 5. What this session changed

- **Browse API** — `repositories/taxonomy.py` (nav tree, category/collection pages) and a rewritten
  `list_products` with facets, sorting and filters.
- **Admin taxonomy CRUD** — `repositories/admin_taxonomy.py`, `routes/admin_taxonomy.py`. No UI yet.
- **Seeds** — `seed_taxonomy.py` (tree, collections, sizes, colours with Arabic labels),
  `seed_demo_catalogue.py` (23 products, drawn placeholder artwork),
  `import_local_images.py` (the user's own photography).
- **Storefront** — nav, category and collection pages, filter sidebar, merchandising homepage,
  upgraded product card, footer, typography and a full design pass.
- **Admin theming** — `admin/src/assets/theme.js` gives Ant Design the storefront's palette.
- **Sitemap** — now carries 15 categories and 6 collections per locale alongside the products.
- **Background queue** — Postgres outbox, `workers/` + `tasks/`; see §9.
- **Cache invalidation after commit** — `services/cache_invalidation.py`.

---

## 6. Traps this session actually hit

- **`overflow-x: clip` on a width-constrained container clips a full-bleed break-out.** It cut the
  hero's own headline off the side of the page. It belongs on `body`. Still `clip` and not `hidden`,
  because `hidden` on an ancestor silently disables `position: sticky`.
- **A level-1 category owns no products and never can.** `products.category_level` is generated as 2,
  so matching only the named category row made every top-level page — the ones the nav and every
  "View all" link point at — permanently empty. It must resolve to itself *plus its children*.
- **`list_id` must default from the slug, not the name.** Two categories may legibly share a name but
  never a slug, and `list_id` is UNIQUE.
- **`ck_collection_products_position` forbids negatives**, so the negative-parking trick that
  `reorder_images` uses is rejected there. Park on a high offset instead.
- **`claim` does not synchronise the ORM session**, and `db.get` returns the identity-mapped copy.
  Writing against a stale one emits an UPDATE missing `status`, which violates a CHECK. Use
  `populate_existing=True`.
- **Flat colour panels read as missing images**, not as placeholders. A grid of solid rectangles
  looks like a page that failed to load.

---

## 7. Photography

**The user supplied their own** (Pexels-licensed shoe and bag photographs). 25 products carry two
each. `scripts/import_local_images.py` re-imports them; the source folders are gitignored, 34 MB, and
redundant once imported.

**Do not try to fetch product images from the internet.** It was tried and rejected —
`scripts/fetch_sample_images.py` leads with the finding. Wikimedia Commons returned a landscape for
"sandal", a nineteenth-century oil painting for "slipper", and a **named competitor's branded
product**. The last is worse than broken: another company's product photograph on the shop's own
listing misleads a shopper and trades on someone else's mark. No query fixes it; the corpus is wrong.

Commons also rate-limited the run, correctly. The script now pauses 3s per request and stops after
three refusals rather than retrying through a limit that exists for good reason.

---

## 8. Findings nobody has fixed

- **`delete_image` deletes files from storage before its transaction commits.** Confirmed still
  present. If the commit fails the row survives and its photograph does not. Two lines — hand the
  storage deletes to `services.cache_invalidation.on_commit`, which is not cache-specific despite
  the name.
- **Deleting an order is impossible** while a converted cart points at it.
  `ck_carts_converted_consistency` forbids `status='converted'` with a NULL `converted_order_id`, so
  the FK's `ON DELETE SET NULL` cannot fire.
- **The dev database accumulates orders.** `test_cart_and_orders.py` places real orders over HTTP and
  never cleans them up.
- **Several stray Vite dev servers** tend to pile up on 5173–5176. Harmless, confusing.
- A product named `shefo` exists, created through the admin. The seed scripts deliberately leave it
  alone; keep it that way when writing anything that regenerates images.

---

## 9. The background queue, in one page

`backend/models/jobs.py` carries the full reasoning; this is what you need before touching it.

**It is a table, not Redis, and that is the point.** `repositories.jobs.enqueue` writes the row on
the *caller's* session and does not commit, so an order and the job that captures its payment commit
together or roll back together.

**No queue library.** The table holds the work, the retry counters and the schedule; Celery or
Dramatiq would duplicate all three somewhere else. RQ was never an option — it needs `os.fork`.

Four things that look wrong until you know why:

- **There is no `done` status.** Success deletes the row, so the dead-letter path is
  `WHERE status = 'dead'` and the table needs no retention policy.
- **A claim is a lease, not a held transaction.** The handler runs on a separate session, because
  holding a transaction open across a third-party HTTP call is how a slow gateway becomes a database
  outage. An expired lease is charged an attempt, so a job that kills its worker dead-letters.
- **Every timestamp comes from the database clock**, never Python's.
- **Recurring work has no beat process.** Each tick schedules the next occurrence if none is
  outstanding; a partial unique index means exactly one worker wins.

**Adding a job:** a handler in `tasks/`, decorated `@task("name")`, imported from `tasks/__init__.py`.
It takes `(db, payload)`, must never commit, and **must be idempotent**.

---

## 10. Decisions the user still owes

1. **Arabic search normalization** — alef/hamza/taa-marbuta folding and diacritic stripping. Open
   since 2026-08-17 and blocking §4.3.
2. **Email provider** — no order confirmations, no newsletter, and the abandoned-cart sweep currently
   has nothing to trigger.
3. **Audit finding F4** — `orders.gross_order_value` is unconstrained.
4. **Concurrent admin edits** — two operators editing one product silently overwrite each other.
5. **Idempotency retention window** — 24h, to be reconciled against whatever payment gateway the user
   brings.

---

## 11. Opening the PRs

```
https://github.com/shefo90/marvel/compare/main...admin-catalog-writes?expand=1
https://github.com/shefo90/marvel/compare/admin-catalog-writes...admin-ui?expand=1
```

Stacked, so review and merge in that order. `gh` is not installed and there is no `GITHUB_TOKEN`, so
they open from those URLs rather than from the command line.
