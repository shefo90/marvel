# Session Handoff — 2026-08-19

For whoever picks this up. Read this, then [`../../../README.md`](../../../README.md) and
[`2026-08-19-admin-ui-design.md`](2026-08-19-admin-ui-design.md).

[`2026-08-18-session-handoff.md`](2026-08-18-session-handoff.md) is superseded: every item in its
§2 is fixed and merged into the branch, and its §4 "what remains" table is out of date.

---

## 1. Where things stand

| | |
|---|---|
| **Branches** | `admin-ui` (this session's work) sits on `admin-catalog-writes`; both pushed. `main` is at `681779c` and has neither |
| **Tests** | **267 backend**, **65 admin**. Build clean. Diagnostics green |
| **Migrations** | `0001`–`0005` applied to the local DB (5432). **Compose (5433) is still at `0004`** |
| **Merge state** | Nothing merged. Two PRs are open to raise — see §5 |

**The whole admin back-office is now built.** All four stages of
[`2026-08-17-admin-back-office-design.md`](2026-08-17-admin-back-office-design.md): catalog writes,
images, offers, and the UI over all of it.

---

## 2. What this session actually changed

### The four whole-branch review fixes (from the previous handoff's §2)
All landed in `6c97284`. Three corrections to that review's own description are recorded in the
commit and in the sdd ledger; the most important is that a bad enum value was not rejected but
**persisted**, making the row unreadable through the ORM afterwards.

### Two real money bugs, both found by running the thing

1. **Every marked-down order was undercharged.** `create_order` computed `line_subtotal` from the
   sale price and *then* subtracted `cart.discount_total`, which is the markdown — so the markdown
   came off twice. A cart displaying 2398.00 was charged 2198.00. Invisible because the seed
   catalogue has no sale price and no test set one. Fixed by routing both paths through
   `repositories/pricing.py`; the parity test now *creates* the condition rather than hoping for it.

2. **Uploaded images 404'd in development.** Vite proxied `/api` but not `/media`. Stored fine,
   recorded fine, served fine by the API — and invisible in the browser. It would have worked in
   production, which is why it would have shipped.

Neither was reachable by a component test. Both came from driving the real app.

### Three gaps the UI exposed in the API
- no categories endpoint existed at all, so the create form was impossible
- `get_product_for_admin` returned 3 base fields while `update_product` accepted 8
- the same for translations: 4 fields read, 8 written — a form rendering all 8 would have wiped
  the SEO and Open Graph metadata on every save

---

## 3. How to work on this — the things that cost time

### 3.1 Drive the real app. It is where the bugs are.
Both money bugs above passed every unit test. The pattern that worked: Playwright installed **into
the scratchpad**, not the project, driving `http://localhost:5173/admin/` against a real API, with
a staff account created and deleted around the run. `console`/`pageerror` listeners caught the
antd v6 deprecations for free.

One trap: `waitForLoadState('networkidle')` fires *before* React paints, so an early screenshot
shows a blank page and the run looks broken when it is not. Wait for a selector.

### 3.2 jsdom cannot round-trip a file upload
`user.upload()` + axios + MSW loses the filename (it becomes `"blob"`) and the bytes. The multipart
body still shows both parts, so assert the parts at the tab level and assert the `File` itself at
the service level, where no transport is in the way. `catalog.service.test.js` does this.

### 3.3 Postgres constraints that shape the code
- `uq_product_images_position` is NULLS NOT DISTINCT **and not deferrable**, so reordering has to
  park every row on a negative position first. One-row-at-a-time collides halfway through.
- `SAEnum(native_enum=False)` creates **no CHECK**. A bad value is written and then makes the row
  unreadable — validate at the Pydantic boundary.
- The partial unique indexes on primary images mean the old primary must be cleared *and flushed*
  before the new one is set.

### 3.4 Environment
- **Docker Desktop stops on its own.** A slow suite (255s vs 15s) means Redis is down, not that the
  tests are slow. `docker compose up -d redis`.
- Pillow is now a dependency; `MEDIA_ROOT` defaults to `backend/media` and is gitignored.
- `verify_triggers.py` used to assert a hardcoded table count and went stale on migration 0005. It
  now derives the count from `Base.metadata`.
- `check_query_count.py` reports "cache cold — Redis is down" and then measures **0 queries** when
  Redis is up and warm. It passes its budget by measuring a cache hit, i.e. it proves nothing in
  that state. Still unfixed.

---

## 4. What remains

| Slice | State |
|---|---|
| **Order management** | ⬜ **Never designed.** The role ladder reserves `operations` for orders, shipments and refunds; no screen, no endpoint. An operator can build the catalogue and cannot see a single order |
| **S2 — storefront & SEO** | ⬜ The big one. React SSR on Vike, bilingual with RTL, full pixishoes parity, JSON-LD, sitemaps, CWV |
| **S3 — browser measurement** | ⬜ dataLayer, GTM, GA4, Meta/TikTok pixels, Consent Mode v2 |
| **S4 — commerce integrations** | ⬜ Payment webhooks, courier adapter, **background queue**, retries |
| **S5/S6/S7** | ⬜ Blocked on S3/S4 |

**The background queue is still the cheapest unlock** — small, and S4, S5 and S6 all wait on it.

### Deferred with rulings — do not rediscover
Everything in §6 of the previous handoff still stands, and all of it still matters:

- **`_invalidate` runs before `db.commit()`** on every admin write path. Must land before S2 ships
  a storefront that can read the cache.
- **No write bumps `catalog_updated_at` / `inventory_updated_at` / `content_updated_at`.** Must be
  fixed before S6 or the incremental feed silently skips every edited variant.
- `repositories/admin_catalog.py` is ~880 lines and holds two responsibilities.
- `_unique_sku`'s SELECT-then-insert is a bounded TOCTOU race.
- `product_path()` in `admin_slugs.py` is provisional — S2 must confirm the `products` segment.
- `is_complete` omits `title`, so it is not a readiness signal. The listing badge says
  published/draft and never "ready".

New, deferred this session:

- **`admin_variant_update` types NOT NULL columns as `X | None`**, so an explicit `null` still
  reaches the flush as a 500.
- **BOGO's line-level comparison does not re-run the chunking** when a line takes the per-unit offer
  instead. The design calls this out as a deliberate simplification; it is deterministic and never
  worse than either offer alone.
- **Variant and collection promotion targets have no UI.** The API supports all five target types;
  the offers form offers `all` and `category`.
- **Empty directories are left behind** when the last image in a hash prefix is deleted.

---

## 5. Decisions needed from the user

1. **Merge the two branches.** `admin-catalog-writes` (17 commits) and `admin-ui` (12) are pushed
   and unmerged. `gh` is not installed, so the PRs open from the compare URLs in §6.
2. **Order management** — the largest undesigned gap, and the operator's next obvious need.
3. **Compose is at migration `0004`.** `docker compose up -d --build api` picks up `0005`; a plain
   `restart` does not, because the image bakes the code in.
4. Everything in §5 of the previous handoff still stands: S2's visual design, Arabic search
   normalization, audit finding F4, concurrent admin edits, and the idempotency retention window.

---

## 6. Opening the PRs

```
https://github.com/shefo90/marvel/compare/main...admin-catalog-writes?expand=1
https://github.com/shefo90/marvel/compare/admin-catalog-writes...admin-ui?expand=1
```

The second is stacked on the first, so review and merge in that order. A ready-to-paste body for
the first is in the scratchpad as `PR_BODY.md` — regenerate it if the scratchpad is gone; the commit
messages carry the same reasoning.
