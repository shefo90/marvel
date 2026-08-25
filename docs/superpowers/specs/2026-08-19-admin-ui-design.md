# Admin UI — Design (back-office Stage 4)

**Status:** approved in conversation 2026-08-19.
**Prerequisite reading:** [`2026-08-17-admin-back-office-design.md`](2026-08-17-admin-back-office-design.md)
(§2 locked decisions, §5 product editor), and the repository-root
`React Front-end Project Structure Documentation (1).pdf`, whose folder structure this follows.

---

## 1. Why

Stage 1 shipped the catalog write API. Nothing consumes it. An operator still cannot add a product
without a developer — the only difference is that the developer now calls an endpoint instead of
writing SQL. This stage is the first thing that makes the back-office real for a human.

It also sets the frontend conventions for a repository that has none: this is the first JavaScript in
the project.

---

## 2. Decisions

Carried from §2 of the back-office design, unchanged:

| Area | Decision |
|---|---|
| Rendering | Vite + React, client-side only. No SSR |
| Interface language | English only. No i18n, no RTL chrome |
| Serving | `marvel.com/admin`, path-based on the same origin |
| Access token | In memory only — never `localStorage` or `sessionStorage` |

Decided for this stage:

| Area | Decision | Why |
|---|---|---|
| Two front ends | `admin/` and, later, `storefront/` are separate apps | They agree on nothing: SSR vs client-only, bilingual RTL vs English, custom styling vs Ant Design, third-party pixels vs a CSP that forbids them |
| Session persistence | Both tokens in memory; a reload means logging in again | The backend has no cookie path (see §3.1). Nothing persisted is the strongest posture, and it defers the cookie work to when admin moves to its own subdomain — the only thing that actually stops a compromised same-origin script |
| UI toolkit | Ant Design | Tables, form validation, modals and toasts are the bulk of an admin panel. Admin styling never has to match the storefront, so none of it needs to carry into S2 |
| Server state | TanStack Query | A list-plus-editor app lives or dies on refetch-after-mutation. Publishing a language must refresh the listing without manual bookkeeping |
| Client state | `context/AuthContext.jsx` only | Auth is the only client state. Redux over two values is ceremony — `store/` is omitted rather than created empty |
| Language | `.jsx` with SCSS modules | The structure PDF specifies both |
| Tests | Vitest + React Testing Library + MSW | The project is TDD throughout; a frontend with no tests would be the first exception |

---

## 3. What the backend is missing

### 3.1 The refresh cookie does not exist

§2.1 of the back-office design lists an `HttpOnly; Secure; SameSite=Strict` refresh cookie as a
required mitigation. It was never implemented. `POST /api/{locale}/auth/staff/login` returns the
refresh token in the JSON body, and `POST /api/{locale}/auth/staff/refresh` reads it from the
`Authorization` header.

This stage does **not** add it. Two reasons: a cookie does not defend against the threat the
mitigation names — a malicious script on the *same origin* can POST to the refresh endpoint, since
the cookie rides along automatically, and read the new access token out of the JSON response — and
the honest fix is the separate `admin.marvel.com` origin the design already anticipates. Holding
nothing at all is strictly safer than holding a 14-day admin credential where a script can reach it.

The cost is a login after every reload. Accepted for a single-operator tool.

### 3.2 There is no categories endpoint

`admin_product_create.category_id` is required, and `create_product` rejects anything that is not a
level-2 category. There is no endpoint anywhere that lists categories — the public router exposes
only `/products` and `/products/{slug}`, and there is no `repositories/categories.py`. The create
form cannot exist without one.

Added here, since nothing else needs it:

```
GET /api/admin/categories  ->  [{id, name, slug, parent_id, parent_name}]
```

Level-2 only, ordered by parent then position, gated at `LEVEL_CATALOG` like the rest of
`/api/admin/*`. Products attach to level-2 categories only (§5.4 of the back-office design), so
returning level-1 rows would offer the operator a choice the database refuses.

---

## 4. Structure

`admin/` sits beside `backend/`. Three siblings when S2 lands: `backend/`, `admin/`, `storefront/`.

```
admin/
├── index.html
├── package.json
├── vite.config.js
├── .env.example
└── src/
    ├── main.jsx              QueryClientProvider, AntD ConfigProvider, BrowserRouter basename="/admin"
    ├── App.jsx               AuthProvider + AppRoutes
    ├── assets/styles/        _variables.scss, _mixins.scss, main.scss
    ├── components/
    │   ├── common/           Loader, ErrorState, PageHeader, BlockerList
    │   └── layout/           AdminLayout, Sidebar, Navbar
    ├── pages/                Login, Products, ProductNew, ProductEdit, NotFound
    ├── services/             api.js, auth.service.js, catalog.service.js, category.service.js
    ├── hooks/                useAuth, useDebounce, useProducts, useProduct, useCategories
    ├── context/              AuthContext.jsx
    ├── routes/               AppRoutes.jsx
    └── utils/                constants.js
```

Each component gets its own folder with a co-located `.module.scss`, per the structure document.

`vite.config.js` carries two settings that matter:

- `base: '/admin/'` — built asset URLs must resolve when the app is served from a path, not a root
- a dev proxy sending `/api` to `http://localhost:8000` — the browser then sees one origin, so no
  CORS middleware is needed on the API, and development matches the production topology instead of
  diverging from it

---

## 5. Auth

`AuthContext` holds `{accessToken, refreshToken, user}` in memory. Nothing is written to any storage.

`services/api.js` is a single axios instance:

- a request interceptor attaching `Authorization: Bearer <access>`
- a response interceptor that, on 401, refreshes once and retries the original request

Three details the interceptor gets wrong if written casually:

1. The refresh call uses a **bare** axios call, not the instrumented instance, or a failing refresh
   recurses into itself.
2. Concurrent 401s share **one** in-flight refresh promise. Ten parallel requests must not fire ten
   rotations — and rotation revokes the presented token, so the second one would fail by design.
3. A retry is attempted **once**. A second 401 clears auth and routes to `/login`.

Tokens reach the module through a setter rather than a React import, keeping `services/api.js` free
of React and honouring the structure document's "centralize API logic here".

**No proactive refresh timer.** The design first called for one at 80% of `expires_in`, to avoid a
401 mid-save. It was dropped during implementation: the reactive path already covers that case
exactly — a save that 401s is refreshed and retried transparently, and the first attempt did nothing,
so the retry is safe. A background timer rotating tokens on its own is one more thing to get wrong
for a case that is already handled.

**Role is read from the JWT payload for display only** — hiding the COGS field below `admin`. The
client never trusts it: `routes/admin_deps.py` re-reads the actor from the database on every request
and returns 403 regardless of what the UI chose to render. This mirrors the backend's own rule that
the token's `access_level` claim is never authoritative on its own.

---

## 6. Screens

### 6.1 Login

Email and password against `/api/en/auth/staff/login`. The `/en/` segment is cosmetic in an
unlocalized admin — open question 3 of the back-office design, deliberately not solved here.

### 6.2 Product listing

Server-paged Ant Design table over `GET /api/admin/products`: `page`, `page_size`, `total`, a status
filter, and a debounced search. Columns: title, slug, status, variant count, image count, and a
per-locale badge.

**The per-locale badge shows published or draft — never "ready".** `is_complete` is a generated
column computed from `description` and `meta_description` only; it omits `title`, which the publish
CHECK requires. A row can therefore read `is_complete` while being unpublishable. `publish_readiness`
is the authoritative signal and it lives in the editor. This is the UI note §6 of the 2026-08-18
handoff asked for.

### 6.3 New product

Title, slug (auto-slugified from the title, editable), brand, category picker (§3.2's endpoint,
level-2 only), and the enum selects — `condition`, `gender`, `age_group` — fed from
`utils/constants.js` mirroring `core/enums.py`. `item_group_id` is optional with a 64-character cap
and the helper text "generated from the slug if left blank", because it is Merchant's variant-grouping
key and is `UNIQUE`.

### 6.4 Product editor

`GET /api/admin/products/{id}` returns the product, its translations and its variants in one call.
Three tabs:

**Basics** — `PATCH /products/{id}` for base fields. Archive sits behind a confirmation and is the
only removal offered; there is no delete, and §5.5 explains why (`fk_order_items_product_id` is
`ON DELETE RESTRICT`, and deleting would orphan the history GA4, Merchant Center and the Meta
catalog key on).

**Content** — one form per locale (`en`, `ar`), saved with `PUT /products/{id}/translations/{locale}`.
A readiness panel calls `GET /products/{id}/readiness?locale=` and Publish posts to
`/publish?locale=`, rendering the structured blocker list when it returns 422. Arabic inputs carry
`dir="rtl"`: that is text direction inside a textbox, not RTL chrome, and does not contradict the
English-only interface decision.

**Variants** — the matrix generator (sizes × colours with shared price, sale price, stock,
availability, size system, material) posting to `/products/{id}/variants`, plus inline row editing
through `PATCH /variants/{id}`. SKU renders read-only with the note that **it is immutable after
save**, which §5.1 requires stated at entry rather than discovered as a trigger error. The COGS field
renders only for `admin`.

Every mutation invalidates `['products']` and `['product', id]`.

---

## 7. Error handling

FastAPI returns `detail` in three different shapes, and a UI that assumes one of them renders
`[object Object]` for the other two:

| Shape | Source | Rendered as |
|---|---|---|
| `"slug already in use"` | 409 conflicts, 400 guards | Field error, or a toast |
| `[{code, message}]` | Publish 422 | The blocker panel |
| `[{loc, msg, type}]` | Pydantic 422 | Per-field errors, mapped through `loc` |

One normalizer in `services/api.js` turns all three into `{status, message, blockers, fieldErrors}`.
Status handling: 401 refresh-then-retry then logout, 403 a permission message (the COGS case), 409 a
field error, 5xx a toast.

---

## 8. Testing

Vitest + React Testing Library + MSW. What must be covered, because each is a place this design can
silently fail:

- the interceptor refreshes once on 401 and retries — and does **not** fire two rotations for two
  concurrent 401s
- a failed refresh clears auth and routes to `/login`
- `RequireAuth` redirects when there is no token
- the listing pages, filters and searches against the server, not in the browser
- the create form surfaces a 409 on the slug field rather than as a toast
- publish renders the blocker list from a 422
- the COGS field is absent for a `catalog` role and present for `admin`

The categories endpoint gets ordinary pytest coverage at both the repository and HTTP levels, as
every other admin endpoint has.

---

## 9. Build order

| Task | Contents |
|---|---|
| **1** | `GET /api/admin/categories` — repository, schema, route, tests |
| **2** | App foundation and auth: Vite, AntD, router, axios interceptors, `AuthContext`, Login, `RequireAuth`, layout shell |
| **3** | Product listing: paging, status filter, debounced search, per-locale badges |
| **4** | Create and Basics: category picker, enum selects, slug auto-fill, PATCH, archive |
| **5** | Content and Variants: per-locale forms, readiness, publish blockers, matrix generator, inline variant editing, COGS gating |

Each task leaves a working application.

---

## 10. Out of scope

- **Production serving.** Whether the built assets sit behind a reverse proxy or a FastAPI
  `StaticFiles` mount is a deployment decision, not a frontend one. `base: '/admin/'` is set so
  either works.
- **The strict `/admin` CSP.** It belongs with whatever serves the app, and there is no such thing
  yet.
- **Images and offers.** Stages 2 and 3 of the back-office are not built; the UI grows to cover them
  when they are.
- **Bulk operations**, per open question 4 of the back-office design.
- **Concurrent edit protection.** Open question 1 there: two operators still overwrite each other
  silently. Unchanged by this stage.
