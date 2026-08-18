# Session Handoff — 2026-08-18

For whoever picks this up. Read this, then
[`2026-08-17-admin-back-office-design.md`](2026-08-17-admin-back-office-design.md) (the approved
design for the work in flight) and [`../../../README.md`](../../../README.md).

The previous handoff, [`2026-08-17-session-handoff.md`](2026-08-17-session-handoff.md), is still
accurate for S1 and the locked decisions. **Do not re-read it for status** — §6 and §8 of it are
superseded by this document.

This document holds what the design docs do not: exact remaining work, and **how to execute it
without repeating this session's mistakes.** §3 is the most valuable part. Read it before dispatching
anything.

---

## 1. Where things stand

| | |
|---|---|
| **Branch** | `admin-catalog-writes`, 15 commits ahead of `main` (`681779c`) |
| **HEAD** | `3a91326` |
| **Tests** | **128 passing**, verified run twice with identical counts, zero data residue |
| **Migrations** | `0001`–`0004` applied to both the local DB (5432) and compose (5433) |
| **Merge state** | **NOT merge-ready.** Four findings outstanding — see §2 |

Every task in [`../plans/2026-08-17-admin-catalog-writes.md`](../plans/2026-08-17-admin-catalog-writes.md)
is implemented and individually review-clean. The **whole-branch** review then found four issues that
per-task review structurally could not see, because they live in the gaps *between* tasks.

Work completed this session, in order:

1. Put the project under git for the first time (it had none) — baseline `cd497ed`
2. Ran the three audits the previous handoff listed as never-run →
   [`2026-08-17-s1-audit-findings.md`](2026-08-17-s1-audit-findings.md)
3. Migration `0004_audit_integrity` — made `order_audit_log` append-only, added `unit_list_price`
   to the money trigger, extended it to DELETE, converted three varchar `'Y'/'N'` flags to boolean
4. Designed and specced the admin back-office, replacing S1b's promotions engine
5. Implemented Stage 1 (catalog writes) — 10 tasks, all committed

### The execution ledger

`.superpowers/sdd/2026-08-17-admin-catalog-writes/progress.md` is **git-ignored but on disk**. It
holds every ruling, every deferred minor, and the commit range per task. If you resume the plan,
read it first — tasks with a `Task N: complete` line are done. `git clean -fdx` destroys it; recover
from `git log` if that happens.

---

## 2. Immediate: four fixes, then merge

These block the merge. All are small and localized. **Specs are exact — do not re-derive them.**

### C1 — Critical. An empty title can be published into the sitemap

`repositories/admin_catalog.py:245` gates publishing with `getattr(tr, f, None) is None`.
`publish_readiness` at line 752 uses `not getattr(tr, f, None)`. So this succeeds:

```
PUT /api/admin/products/{id}/translations/ar
{"title": "", "description": "d", "meta_description": "m", "is_published": true}
```

`""` is not None so the gate passes. The DB CHECK is NULL-only so it passes. And `is_complete` is
`GENERATED ALWAYS` from description + meta_description **only** — title is not in its expression —
so the row lands `is_published AND is_complete`, joining the hreflang cluster and
`ix_product_translations_sitemap`. A published, sitemap-submitted URL with an empty `<title>`.

Add near `_PUBLISHABLE_FIELDS` (~line 40):

```python
def _missing_publishable_fields(tr) -> list[str]:
    """Which fields ck_product_translations_published_requires_content still needs.

    ONE implementation, called by both upsert_translation and publish_readiness.
    They previously disagreed — `is None` in one, falsiness in the other — so an
    empty or whitespace-only title published through upsert_translation while
    publish_readiness would have refused it. services/identity.py's docstring
    records the same failure mode for customer identity: two implementations of
    one rule that drifted apart.
    """
    return [f for f in _PUBLISHABLE_FIELDS if not (getattr(tr, f, None) or "").strip()]
```

Then replace both call sites (line 245 and line 752) with `missing = _missing_publishable_fields(tr)`.

Tests: `title=""` → 422; `title="   "` → 422; row stays unpublished; readiness agrees.

### C2 — Important. Repeated renames corrupt redirects

`repositories/admin_slugs.py`'s `record_slug_change` blind-inserts against
`uq_url_redirects_locale_from_fold`. Rename a published translation a→b→a→b:

1. The second insert of `/ar/products/a` raises an uncaught `IntegrityError` → 500, losing the rename
2. Redirects are **entity-targeted** (`entity_id`, not `to_path`), so after a→b→a the row
   `/ar/products/a → entity X` is still active while X now *lives* at `a` — S2's resolver would 301
   that URL to itself
3. `uq_product_translations_locale_slug` frees the retired slug, so a different product Y can later
   take `a`; the stale row then silently 301s a live URL to the **wrong product**

Fix: make `record_slug_change` idempotent and self-healing. On conflict with an existing
`(locale, from_path_fold)` row, re-point it at the current entity and reactivate rather than raising.
Also delete or deactivate any redirect row whose `from_path` equals the slug being moved **to** —
that path is now live and must not redirect.

Tests: a→b→a→b succeeds; after a→b→a no active redirect from `a` remains; a conflicting row is
re-pointed, not duplicated.

### I3 — Important. `except IntegrityError` mislabels unrelated violations

`create_product:175` and `update_product` both catch `IntegrityError` and unconditionally raise
`409 "slug already in use"`. So `PATCH` with `{"title": null}` — a NOT NULL violation — returns
`409 "slug already in use"`.

Fix: inspect `e.orig.diag.constraint_name` before deciding. Slug 409 only for the slug-uniqueness
constraint; a separate message for `item_group_id`; re-raise anything else. Guard against `e.orig`
or `.diag` being absent.

### B2 — Important. Validation gaps reaching the DB as 500s

- `generate_variants` lacks the negative-money guards `update_variant` already has — a negative
  `price` or `stock_quantity` hits `ck_variants_price_non_negative` /
  `ck_variants_stock_non_negative` as an uncaught 500. Add them, plus `ge=0` on
  `admin_variant_matrix.price`, `sale_price`, `stock_quantity`.
- `admin_product_create.condition`, `gender`, `age_group` and the `?status=` listing filter are
  unvalidated strings fed into `SAEnum(native_enum=False)` columns — a bad value raises
  `LookupError` → 500. Constrain them against the real enums in `core/enums.py`.
- Add `max_length=64` to `admin_product_create.item_group_id` (column is `String(64)`; a longer
  value plus a long colour overflows the generated `sku String(64)`).

### Then

Run the suite twice, confirm 128+ and identical counts, merge to `main`, delete
`.superpowers/sdd/2026-08-17-admin-catalog-writes/`.

---

## 3. How to work fast — read this before dispatching anything

This session produced good code slowly. Here is precisely where the time went.

### 3.1 Verify plan code against the live database *before* writing the plan

**Four defects in the implementation plan were mine**, and each cost a full fix round:

| Plan defect | What the DB actually said |
|---|---|
| `tr.is_complete = all(...)` | `is_complete` is `GENERATED ALWAYS ... STORED` — cannot be assigned |
| `_variant_sku` used `ch.isalnum()` | Unicode-aware, so Arabic survives and produces a CHECK-invalid SKU; `38.5`/`385` and `M/L`/`ML` collapsed to identical SKUs |
| `e2e_cleanup` nulled `default_variant_id` | Violates `ck_products_active_has_default_variant` on a published product |
| `400 SKU is immutable` in `update_variant` | Unreachable — `admin_variant_update` had no `sku` field, so Pydantic dropped it and the caller got a silent `200` |

A pre-flight scan caught four *different* problems and none of these. **The lesson: dump the live
schema and grep it before writing plan code.** Specifically check `is_generated`,
`generation_expression`, every CHECK constraint, and whether the Pydantic schema actually carries
each field the repository branches on. Ten minutes of `information_schema` queries would have saved
four fix rounds.

Useful probes already in the repo: `scripts/audit_approach_a.py`, `scripts/audit_audit_log_tamper.py`,
`scripts/verify_triggers.py`, `scripts/check_query_count.py`.

### 3.2 Review per stage, not per task (decided with the user)

Per-task review cost ~3 agent dispatches per task (implement → review → fix → re-review). Ten tasks
became ~15 dispatches at 70–200k tokens each. That is the single biggest time sink, and it is why two
session limits were hit.

**What the evidence actually showed:** per-task reviews found mostly minors. Both serious bugs — C1
and C2 above — were found only by the **whole-branch** review, because they live in the gaps between
tasks that a task-scoped reviewer cannot see.

So: batch implementation into one or two dispatches per stage, then run **one whole-branch review per
stage** on the most capable model. Keep TDD inside the implementer. Do not drop the whole-branch
review — it is the step that earns its keep.

### 3.3 Batch same-shape tasks

Tasks 8+9+10 (repository function + schema + route + tests, same three files) went out as one
dispatch and reviewed cleanly as one diff. Tasks 6+7 likewise. Reserve one-dispatch-per-task for work
needing its own judgment.

### 3.4 Weigh subagent pushback on evidence, not authority

An implementer pushed back on a finding I had escalated (I claimed `gender=None` overrode a
`server_default` and would fail Merchant validation). It was right; I verified and reversed. Another
time an agent's report claimed a review passed when it had actually tripped an unrelated constraint —
retesting showed the attack succeeded. **Verify claims that matter, in both directions.** Do not
rubber-stamp reports, and do not dismiss a pushback that comes with evidence.

### 3.5 Infrastructure notes that cost real time

- **Redis must be up** or the suite takes 255s instead of ~7s. Multiple agents wasted turns on this.
  `docker compose up -d redis` from the repo root.
- **The console is cp1252.** Printing Arabic raises `UnicodeEncodeError`. Set
  `PYTHONIOENCODING=utf-8`, and prefer `\uXXXX` escapes in test source.
- **The compose API image bakes the code in.** `docker compose restart api` does *not* pick up a new
  migration; `docker compose up -d --build api` does.
- **The `Agent` and `Bash` tools were intermittently unavailable** at the end of this session (the
  authorizing classifier depends on Opus, which was overloaded). Read-only tools kept working. If it
  happens again, do not burn turns retrying — write the fix specification down and continue when it
  clears.

### 3.6 Do not re-litigate

The locked decisions in §3 of the previous handoff still hold. Additionally settled this session:
Egypt/EGP only, admin at `marvel.com/admin` path-based (with in-memory access token, HttpOnly refresh
cookie, and a strict CSP on `/admin` as the agreed mitigations), per-language publishing with drafts,
best-single-discount-wins with no stacking, no coupon codes, scheduling on promotions only, and no
hard deletes.

---

## 4. What remains

### Backend — roughly 40% done

| Slice | Scope | State |
|---|---|---|
| **S1 — commerce core** | Identifier contract, catalog/order/payment/attribution/profit schemas, auth, idempotent orders | ✅ Done |
| **Admin Stage 1 — catalog writes** | Product/variant/translation/publish API | 🔄 4 fixes from merge (§2) |
| **Admin Stage 2 — images** | Upload, decode-based validation, SVG rejected, EXIF stripped, derivatives, storage interface, Docker volume. Adds Pillow | ⬜ |
| **Admin Stage 3 — offers** | `promotions` + `promotion_targets`, migration `0005`, ONE pricing implementation shared by cart and checkout, BOGO, proportional refund rule | ⬜ |
| **S4 — Commerce integrations** | Payment webhooks, courier adapter, **background queue**, retries | ⬜ |
| **S5 — Server measurement** | sGTM, Meta CAPI, GA4 MP, Ads offline Delivered | ⬜ blocked on S3+S4 |
| **S6 — Catalogs & BI** | Merchant API v1, catalog adapters, reconciliation, profit dashboards | ⬜ blocked on S4 |
| **S7 — QA & handover** | §15 acceptance tests, alert simulation, docs | ⬜ blocked on all |

**The background queue is the cheapest unlock left** — small, and S4, S5 and S6 all wait on it.
Redis is already in the stack, so RQ/arq/Celery is additive: `workers/` + `tasks/` top-level dirs
following the existing layer-first convention.

### Frontend — 0%. Nothing exists.

| Piece | Scope |
|---|---|
| **Admin Stage 4 — admin UI** | The screens the operator clicks. Nothing in the back-office is usable without it. Plain client-side Vite + React, no SSR, no i18n, no RTL — the easy frontend |
| **S2 — Storefront & SEO** | React SSR on Vike. Full pixishoes parity, functionality *and* style. Bilingual with RTL, URL/indexability contract, JSON-LD, sitemaps, CWV |
| **S3 — Browser measurement** | dataLayer service, GTM environments, GA4, Meta/TikTok pixels, Consent Mode v2 |

**The frontend is ~60% of the remaining work.** S2 alone is larger than all four admin backend stages
combined.

### Recommended order

1. **The four fixes, then merge Stage 1** — leaves the tree clean
2. **Admin Stage 4 (the UI)** — first thing that makes the product real for a human, and the
   simplest React work in the project. Good place to establish frontend conventions before S2's
   harder constraints
3. **Background queue** — small, unblocks three slices
4. **Admin Stages 2 and 3** (images, offers) — Stage 3's migration is the one that is painful to
   change once orders reference it
5. **S2**, then **S3**, then **S4/S5/S6**, then **S7**

If visible progress matters more than structural progress, 2 before 3. If the reverse, swap them.

---

## 5. Decisions needed from the user

These will stall work if not answered when reached.

1. **S2 visual design — the biggest one.** "Full pixishoes parity, functionality *and* style" is
   agreed, but nobody has specified the product card, PDP, cart drawer, or how the size/colour
   selector behaves in RTL. This is the most likely thing to stall S2. It needs a real design pass,
   not a code decision.
2. **Arabic search normalization** — alef/hamza/taa-marbuta folding and diacritic stripping. Without
   it Arabic site search returns wrong results, and §5 requires a `search` event.
3. **Audit finding F4** — `orders.gross_order_value` is unconstrained. §5.3 defines it as the value
   *at creation*, so it should legitimately diverge from `total` after corrections; the right guard
   is immutability after insert, but that forecloses same-day restatement of a mis-keyed order.
4. **Concurrent admin edits** — two operators editing one product silently overwrite each other. Zero
   risk with one operator; a real problem the day a second is hired.
5. **Idempotency retention window** (carried from the previous handoff, still urgent) — currently 24h,
   must be reconciled against the payment gateway's retry horizon **before any gateway goes live**.

---

## 6. Deferred with rulings — do not rediscover these

From the whole-branch review, deliberately not fixed:

- **`_invalidate` runs before `db.commit()`** on all six write paths, so a concurrent storefront read
  in that window can re-cache pre-commit rows for up to `TTL_PRICING` (60s). Real but tiny window;
  the fix restructures nine routes. **Must land before S2** ships a storefront that can read the cache.
- **No write bumps `catalog_updated_at`, `inventory_updated_at`, or `content_updated_at`.** They have
  `server_default` but no `onupdate` and no trigger. `ix_product_variants_feed_pending` is labelled
  "incremental catalog sync" and the sitemap indexes carry `<lastmod>`. **Must be fixed before S6** or
  the feed silently skips every edited variant.
- **`repositories/admin_catalog.py` is 810 lines and holds two responsibilities.** The seam:
  `_clean_sku_segment`, `_variant_sku`, `_unique_sku`, `generate_variants`, `update_variant` →
  `repositories/admin_variants.py`. Cohesion, not correctness.
- **`_unique_sku` SELECT-then-insert is a TOCTOU race** under concurrent admin writes. Bounded — the
  UNIQUE index holds, so it is a 500, never a duplicate identifier.
- **`record_slug_change`'s `from_path` shape (`/{locale}/products/{slug}`) is provisional** — no
  storefront exists yet to confirm the `products` segment. S2 must re-check it.
- **`is_complete` omits `title`** from its generated expression while the publish CHECK requires it.
  The admin listing surfaces `is_complete` per locale, so on its own it is a misleading readiness
  signal. `publish_readiness`'s blocker list is authoritative. **Worth a UI note in Stage 4.**
- Minor: non-ASCII punctuation survives slug normalization; `e2e_cleanup` registers its slug only
  after both HTTP calls succeed; the dimensions schema addition has no HTTP-level test.

---

## 7. Environment

Unchanged from the previous handoff except where noted:

- **Python 3.12**, not 3.14 — `psycopg2-binary` has no 3.14 wheel. Venv at `backend/.venv`.
- **Tests run against the user's own Postgres on `localhost:5432`** (`postgres`/`123`/`postgres`),
  per `backend/.env`, which is gitignored. Compose uses its own isolated Postgres on **5433**.
  Both are at migration `0004`.
- **A git worktree will not work for this project** — `backend/.env` is gitignored, so a fresh
  worktree has no DB config and cannot run a single test. Use a branch.
- `.gitignore` now covers `.env`, `.venv`, `__pycache__`, `.claude/settings.local.json`,
  `node_modules`, and `backend/scratch_out.txt`.
