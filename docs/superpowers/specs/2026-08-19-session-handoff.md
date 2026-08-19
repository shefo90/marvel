# Session Handoff — 2026-08-19

For whoever picks this up. Read this, then [`../../../README.md`](../../../README.md).

[`2026-08-18-session-handoff.md`](2026-08-18-session-handoff.md) is superseded entirely.

---

## 1. Where things stand

| | |
|---|---|
| **Branches** | `admin-ui` holds everything; it sits on `admin-catalog-writes`. Both pushed. `main` is at `681779c` and has neither |
| **Tests** | **305 backend**, **70 admin**, **50 storefront**. All builds clean |
| **Migrations** | `0001`–`0005` on the local DB (5432). **Compose (5433) is still at `0004`** |

**A shopper can now buy something.** Browse in either language, add to a cart, check out with cash
on delivery, and an operator sees the order and moves it along. That was not true this morning.

---

## 2. What exists now

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

## 3. Blocked on the user, not on work

Three things cannot proceed without decisions or credentials only they have:

1. **Payment gateway** — which Egyptian provider (Paymob, Fawry, …) and its keys. COD works, so the
   shop can trade meanwhile.
2. **Measurement IDs** — GTM container, GA4 property, Meta pixel + CAPI token, TikTok. The full
   event contract is built and tested; the ids are env vars (`GTM_CONTAINER_ID`).
3. **Visual reference for "pixishoes parity"** — no access to that site. The storefront has a
   clean design of its own and the entire URL/SEO contract; matching their look needs screenshots.

---

## 4. Bugs found by running the thing, not by testing it

This is the section worth reading. Every one of these passed the unit tests.

- **Every marked-down order was undercharged.** `create_order` subtracted the markdown twice. A
  cart showing 2398.00 was charged 2198.00. Invisible because the seed catalogue has no sale price
  and no test set one — the parity test now *creates* the condition.
- **The variant table never refreshed.** `useParams` gives a string id, the payload gives a number,
  so `['product','7']` and `['product',7]` were different cache entries.
- **Uploaded images 404'd in development.** Vite proxied `/api` but not `/media`.
- **The image fallback never fired on a cold load.** On a server-rendered page the image fails
  *before* React hydrates, so `onError` never sees it. Needed a post-mount
  `complete && naturalWidth === 0` check.
- **`view_item_list` carried no `item_id`.** The listing API returned no SKU, and the unit test
  passed only because its fixture invented a field the API does not return — it was checking the
  mock, not the contract.

**The lesson, again:** drive the real app and read the real output. A browser, a screenshot, and a
dump of `window.dataLayer` found five defects that 425 tests did not.

---

## 5. Two findings I did not fix

- **Deleting an order is impossible** while a converted cart points at it.
  `ck_carts_converted_consistency` forbids `status='converted'` with a NULL `converted_order_id`, so
  the FK's `ON DELETE SET NULL` cannot fire. The README tells people to clean up test data by
  deleting the order; that path does not work. Move the cart out of `converted` first, or make the
  FK `ON DELETE CASCADE` for carts.
- **The dev database has ~755 orders.** `test_cart_and_orders.py` places real orders over HTTP and
  never cleans them up, so every suite run adds more. Not harmful, but it is why the number is
  large, and combined with the above it is awkward to clear.

---

## 6. Still deferred, with the deadlines that matter

Carried forward and still true:

- **`_invalidate` runs before `db.commit()`** on every admin write path. The storefront now reads
  that cache, so this window is live rather than theoretical. **Fix next.**
- **No write bumps `catalog_updated_at` / `inventory_updated_at` / `content_updated_at`.** Must be
  fixed before S6 or the incremental feed silently skips every edited variant.
- `repositories/admin_catalog.py` is ~900 lines and holds two responsibilities.
- `admin_variant_update` types NOT NULL columns as `X | None`, so an explicit `null` is a 500.
- `check_query_count.py` measures a cache hit when Redis is warm, so it proves nothing in that state.

New, from the S2 work — all from §6.7's RTL contract, which is worth reading in full before
touching the storefront:

- **No self-hosted font.** The contract specifies a dual-script family (IBM Plex Sans Arabic or
  similar), two weights, subset by unicode-range, `font-display: swap`, one preload per route chosen
  server-side. The storefront currently uses a system stack.
- **No locale-scoped line-height token** (`[lang="ar"] { --line-height-body: 1.75 }`).
- **No CI lint** over the built bundle for banned client-side `dir`/`lang` assignment.
- **No i18n files.** UI strings are inline `COPY` objects per component, not `locales/en.json` +
  `locales/ar.json` with the six Arabic plural categories. Fine at this size; it is not what §6.6
  describes.
- **No category or collection pages, and no search.** The storefront has a home listing and a PDP.
  §5 requires a `search` event, and Arabic search needs the alef/hamza/taa-marbuta folding that is
  still an open question.

---

## 7. Recommended order

1. **Merge.** Two branches, both pushed, neither merged. §8 has the URLs.
2. **The `_invalidate`-before-commit fix** — now that a storefront reads the cache.
3. **Background queue** — small, and S4, S5 and S6 all wait on it.
4. **Payment gateway** once the provider is chosen; **courier** likewise.
5. **S5 server measurement** — needs the same credentials as S3.
6. **S6 feeds**, then **S7**.

---

## 8. Opening the PRs

```
https://github.com/shefo90/marvel/compare/main...admin-catalog-writes?expand=1
https://github.com/shefo90/marvel/compare/admin-catalog-writes...admin-ui?expand=1
```

Stacked, so review and merge in that order. `gh` is not installed here, so they open from those
URLs rather than from the command line.
