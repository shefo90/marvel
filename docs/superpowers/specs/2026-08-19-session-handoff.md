# Session Handoff — 2026-08-19

**Start here.** Then [`../../../README.md`](../../../README.md). Everything before this document is
superseded — including [`2026-08-18-session-handoff.md`](2026-08-18-session-handoff.md), whose every
open item is now closed.

---

## 1. The first ten minutes

```bash
docker compose up -d redis        # or the test suite takes 255s instead of 20s

cd backend
.venv\Scripts\python -m pytest -q             # expect 305 passed
.venv\Scripts\python -m uvicorn main:app --port 8000

cd ../storefront && npm install && npm run dev   # http://localhost:3000
cd ../admin      && npm install && npm run dev   # http://localhost:5173/admin/
```

The admin needs a staff account; there is no registration screen:

```bash
cd backend
.venv\Scripts\python -c "from core.db import SessionLocal; from repositories.register import create_staff_user; db=SessionLocal(); create_staff_user(db, email='you@example.com', password='choose-one', full_name='You', role='admin'); db.close()"
```

**Python 3.12, not 3.14** — `psycopg2-binary` has no 3.14 wheel. Venv at `backend/.venv`. Tests run
against the user's own Postgres on **5432** (`postgres`/`123`/`postgres`, from the gitignored
`backend/.env`); compose has its own on 5433. **A git worktree will not work** — `.env` is
gitignored, so a fresh worktree cannot run a single test. Use a branch.

---

## 2. Where things stand

| | |
|---|---|
| **Branch** | `admin-ui` (41 commits ahead of `main`), stacked on `admin-catalog-writes` (17). Both pushed |
| **`main`** | `681779c` — has none of it |
| **Tests** | **305 backend**, **70 admin**, **50 storefront**. All green, all builds clean |
| **Migrations** | `0001`–`0005` on the local DB. **Compose (5433) is still at `0004`** — `docker compose up -d --build api` picks it up; a plain `restart` does not, because the image bakes the code in |

**A shopper can buy something.** Browse in Arabic or English, add to a cart, check out with cash on
delivery; an operator sees the order and moves it along.

| Slice | State |
|---|---|
| S1 commerce core | Done |
| Admin stages 1–4 (catalog, images, offers, UI) | Done |
| Order management | Done — the `operations` role, reserved since S1, is finally used |
| S2 storefront & SEO | Done — SSR on Vike, bilingual, RTL, sitemaps, JSON-LD, hreflang |
| S3 browser measurement | Done — dataLayer, GA4 ecommerce events, Consent Mode v2 |
| S4 commerce integrations | **COD only.** No gateway, no courier, no background queue |
| S5 server measurement | Not started |
| S6 catalogs & BI | Not started |
| S7 QA & handover | Not started |

---

## 3. What to do next

**Do these three first. None of them needs anything from the user.**

1. **`_invalidate` runs before `db.commit()`** on every admin write path. This was deferred twice as
   theoretical because nothing read the cache. **The storefront now reads it**, so a shopper can be
   served a pre-commit price for up to `TTL_PRICING` (60s). It is a live bug as of today. The fix
   restructures nine routes in `repositories/admin_catalog.py` and `admin_images.py`.
2. **Background queue.** Small, additive — Redis is already in the stack — and S4, S5 and S6 all
   wait on it. `workers/` + `tasks/` as top-level directories, following the layer-first convention.
   Nothing else unblocks three slices for so little.
3. **Merge.** Two stacked branches, 41 commits, neither on `main`. §8 has the URLs.

Then, in order: payment gateway → courier → S5 server measurement → S6 feeds → S7.

### Blocked on the user, not on effort

| | What is needed |
|---|---|
| Payment gateway | Which Egyptian provider (Paymob, Fawry, …) and its API keys |
| Server measurement (S5) | GA4 property, Meta CAPI token, sGTM endpoint |
| Courier adapter | Which courier (Bosta, Aramex, …) and credentials |
| Storefront visual parity | Screenshots or a URL for pixishoes — "full parity, functionality *and* style" is agreed but nobody has seen the reference |

---

## 4. How to work on this

**Drive the real app. It is where the bugs are.** Five defects this session passed every unit test
and were found only by running the thing:

- **Every marked-down order was undercharged** — `create_order` subtracted the markdown twice. A
  cart showing 2398.00 charged 2198.00. Invisible because the seed catalogue has no sale price and
  no test set one.
- **The variant table never refreshed** — `useParams` gives a string id, the payload a number, so
  `['product','7']` and `['product',7]` were different cache entries.
- **Uploaded images 404'd in development** — Vite proxied `/api` but not `/media`.
- **The image fallback never fired on a cold load** — on an SSR page the image fails *before* React
  hydrates, so `onError` never sees it. Needs a post-mount `complete && naturalWidth === 0` check.
- **`view_item_list` carried no `item_id`** — the listing API returned no SKU, and the unit test
  passed only because its fixture invented a field the API does not return. It was checking the
  mock, not the contract.

What worked: Playwright installed **into the scratchpad**, not the project, driving the real stack;
`console`/`pageerror` listeners; screenshots read with actual eyes; and dumping `window.dataLayer`
through a whole purchase.

Two traps in that loop:

- `waitForLoadState('networkidle')` fires **before** React paints, so an early screenshot shows a
  blank page and the run looks broken when it is not. Wait for a selector.
- **jsdom cannot round-trip a file upload.** `user.upload()` + axios + MSW loses the filename (it
  becomes `"blob"`) and the bytes. Assert the multipart parts at the component level and the `File`
  itself at the service level, where no transport is in the way.

**Read the design docs before building against the schema.** §6.6 and §6.7 of
[`2026-08-16-s1-commerce-core-design.md`](2026-08-16-s1-commerce-core-design.md) are prescriptive
and I violated three points before reading them properly: Western digits in *both* locales, the
server owning `<html lang/dir>`, and locale switching being a full navigation.

---

## 5. Two findings nobody has fixed

- **Deleting an order is impossible** while a converted cart points at it.
  `ck_carts_converted_consistency` forbids `status='converted'` with a NULL `converted_order_id`, so
  the FK's `ON DELETE SET NULL` cannot fire. The README tells people to clean up test data by
  deleting the order — that path does not work. Move the cart out of `converted` first, or make the
  cart FK `ON DELETE CASCADE`.
- **The dev database holds ~755 orders.** `test_cart_and_orders.py` places real orders over HTTP and
  never cleans them up, so every suite run adds more. Harmless, but combined with the above it is
  awkward to clear.

---

## 6. Deferred, with the deadline that makes each one matter

- **`_invalidate` before commit** — see §3. No longer deferrable.
- **No write bumps `catalog_updated_at` / `inventory_updated_at` / `content_updated_at`.** They have
  `server_default` but no `onupdate` and no trigger. **Must be fixed before S6**, or the incremental
  feed silently skips every edited variant.
- `repositories/admin_catalog.py` is ~900 lines and holds two responsibilities. Cohesion, not
  correctness.
- `admin_variant_update` types NOT NULL columns as `X | None`, so an explicit `null` is a 500.
- `_unique_sku`'s SELECT-then-insert is a bounded TOCTOU race — the UNIQUE index holds, so it is a
  500, never a duplicate identifier.
- `check_query_count.py` measures a cache **hit** when Redis is warm, so it proves nothing in that
  state and still reports "cache cold — Redis is down".
- BOGO's line-level comparison does not re-run the chunking when a line takes the per-unit offer
  instead. The design calls this a deliberate simplification; it is deterministic and never worse
  than either offer alone.
- Promotion targets of type `variant` and `collection` have no UI. The API supports all five.

### From §6.7's RTL contract, still outstanding

- **No self-hosted font.** The contract specifies a dual-script family (IBM Plex Sans Arabic or
  similar), two weights, subset by unicode-range, `font-display: swap`, one preload per route chosen
  server-side. The storefront uses a system stack.
- **No locale-scoped line-height token** (`[lang="ar"] { --line-height-body: 1.75 }`).
- **No CI lint** over the built bundle for banned client-side `dir`/`lang` assignment.
- **No i18n files.** UI strings are inline `COPY` objects per component rather than
  `locales/en.json` + `locales/ar.json` with the six Arabic plural categories. Fine at this size; it
  is not what §6.6 describes.

---

## 7. The biggest product gap

The storefront has a **home listing and a product page**. There are no category pages, no collection
pages, and **no search**. §5 requires a `search` event, and Arabic search needs the
alef/hamza/taa-marbuta folding and diacritic stripping that has been an open question since the
2026-08-17 handoff — without it, Arabic site search returns wrong results.

That is the largest remaining gap in the *product*, as opposed to the plumbing.

---

## 8. Opening the PRs

```
https://github.com/shefo90/marvel/compare/main...admin-catalog-writes?expand=1
https://github.com/shefo90/marvel/compare/admin-catalog-writes...admin-ui?expand=1
```

Stacked, so review and merge in that order. `gh` is not installed here and there is no
`GITHUB_TOKEN`, so they open from those URLs rather than from the command line.

---

## 9. Decisions the user still owes

Carried from earlier handoffs, none of them answered:

1. **Arabic search normalization** — blocks the search above.
2. **Audit finding F4** — `orders.gross_order_value` is unconstrained. §5.3 defines it as the value
   at creation, so it should legitimately diverge from `total` after corrections; the right guard is
   immutability after insert, but that forecloses same-day restatement of a mis-keyed order.
3. **Concurrent admin edits** — two operators editing one product silently overwrite each other.
   Zero risk with one operator; a real problem the day a second is hired.
4. **Idempotency retention window** — currently 24h, and it must be reconciled against the payment
   gateway's retry horizon **before any gateway goes live**. A window shorter than that horizon lets
   a late retry slip past replay protection and duplicate an order.
