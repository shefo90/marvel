# Admin Back-Office Stage 1 — Catalog Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the shop operator API endpoints to create, edit and publish products, variants and bilingual content — replacing `scripts/seed.py` as the only way a product can exist.

**Architecture:** New write endpoints in the existing `/api/admin` namespace (already gated by `staff_at_least`). Routes do HTTP, repositories do SQL and business rules, schema holds Pydantic contracts — the layering the project already follows. No new tables; Stage 1 writes to the S1 schema as-is.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic, pytest, Postgres 17, Redis.

**Spec:** [`docs/superpowers/specs/2026-08-17-admin-back-office-design.md`](../specs/2026-08-17-admin-back-office-design.md) — §3 (access), §5 (product editor), §7 (cache), §8A stage 1.

## Global Constraints

- **Python 3.12**, not 3.14. Interpreter: `backend/.venv/Scripts/python.exe`.
- **Redis must be running** before the suite: `docker compose up -d redis`. 1.3s with, 255s without.
- **Run tests from `backend/`**: `.venv\Scripts\python.exe -m pytest tests -q`
- **TDD is mandatory.** Write the test, watch it fail for the right reason, then implement.
- **No SQLAlchemy in `routes/`.** No HTTP concepts in `repositories/`.
- **All money is EGP**, VAT-inclusive, `Numeric(12, 2)`. `orders.tax_total` stays 0.
- **Enum values** (from `core/enums.py`): `ProductStatus` = `draft|active|archived`; `ProductCondition` = `new|refurbished|used`; `Gender` = `male|female|unisex`; `Availability` = `in_stock|out_of_stock|preorder|backorder`.
- **`translation_source`** is a plain string column constrained to `human|machine|fallback_en`.
- **Slug formats:** base `products.slug` must match `^[a-z0-9]+(-[a-z0-9]+)*$` (ASCII). Translation slugs use a *denylist* (migration 0003) so real Arabic text is valid — lowercase, no whitespace, no `[A-Z]`, no punctuation, no leading/trailing/doubled hyphen, no invisible characters.
- **SKU format:** `^[A-Z0-9][A-Z0-9-]*$`, globally `UNIQUE`, and **immutable** — `trg_variants_sku_immutable` raises on UPDATE.
- **Products attach to level-2 categories only.** `products.category_level` is `GENERATED ALWAYS AS 2` with a composite FK to `categories(id, level)`.
- **Cache:** always call `cache.invalidate_product(product_id, slugs_by_locale)` after a write. `slugs_by_locale` must include **every** locale the product has, or that locale keeps serving stale content.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/schema/admin_catalog.py` | *(exists)* Pydantic contracts. Gains request/response models. |
| `backend/repositories/admin_catalog.py` | *(exists)* All catalog reads/writes for the back-office. Gains create/update/publish. |
| `backend/repositories/admin_slugs.py` | **Create.** Slug normalization + redirect writing. Isolated because the Arabic rules are subtle and used by three call sites. |
| `backend/routes/admin_catalog.py` | *(exists)* HTTP layer. Gains POST/PATCH/PUT endpoints. |
| `backend/tests/test_admin_catalog.py` | *(exists)* HTTP-level tests with real staff logins. |
| `backend/tests/test_admin_writes.py` | **Create.** Repository-level tests on the rolled-back session. |

---

### Task 1: Create a draft product

**Files:**
- Modify: `backend/schema/admin_catalog.py`
- Modify: `backend/repositories/admin_catalog.py`
- Modify: `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py` (create)

**Interfaces:**
- Consumes: `require_staff(db, claims, minimum_level) -> User` from `repositories/staff_access.py`; `staff_at_least(level)` from `routes/admin_deps.py`.
- Produces: `create_product(db, actor, payload: dict) -> Product`. Route `POST /api/admin/products` returning `admin_product_detail`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py
"""Repository-level admin catalog writes, on the rolled-back session."""

import pytest
from fastapi import HTTPException

from models.categories import Category
from models.users import User
from repositories.admin_catalog import create_product


def _level2_category(db) -> Category:
    """Products attach only to level-2 categories (category_level is generated)."""
    top = Category(
        parent_id=None, level=1, name="W1", slug="w-plan-top",
        list_id="w_plan_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="W2", slug="w-plan-child",
        list_id="w_plan_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _actor(db) -> User:
    user = User(
        email="plan-writer@example.com", password_hash="x",
        full_name="Writer", role="catalog", is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def test_new_product_starts_as_a_draft(db):
    cat = _level2_category(db)
    product = create_product(db, _actor(db), {
        "title": "Suede Sandal", "slug": "suede-sandal",
        "brand": "Pixi", "category_id": cat.id,
    })
    assert product.status == "draft"


def test_item_group_id_is_generated_when_not_supplied(db):
    """It is Merchant's variant-grouping key and UNIQUE — never typed by hand."""
    cat = _level2_category(db)
    product = create_product(db, _actor(db), {
        "title": "Suede Sandal", "slug": "suede-sandal-2",
        "brand": "Pixi", "category_id": cat.id,
    })
    assert product.item_group_id
    assert product.item_group_id == product.item_group_id.upper()


def test_duplicate_slug_is_rejected_with_409(db):
    cat = _level2_category(db)
    base = {"title": "A", "brand": "Pixi", "category_id": cat.id, "slug": "dup-slug"}
    create_product(db, _actor(db), base)
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), dict(base, title="B"))
    assert exc.value.status_code == 409


def test_level_1_category_is_rejected(db):
    """The composite FK to categories(id, level) would fail with a raw 500."""
    top = Category(
        parent_id=None, level=1, name="T", slug="w-plan-only-top",
        list_id="w_plan_only_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    with pytest.raises(HTTPException) as exc:
        create_product(db, _actor(db), {
            "title": "X", "slug": "x-prod", "brand": "Pixi", "category_id": top.id,
        })
    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'create_product'`.

- [ ] **Step 3: Implement `create_product`**

```python
# backend/repositories/admin_catalog.py  — append

import re
import secrets

from fastapi import HTTPException, status

from models.categories import Category

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _generate_item_group_id(slug: str) -> str:
    """Merchant's variant-grouping key. Derived, never typed.

    Uppercased alphanumerics from the slug plus a short random suffix, because
    item_group_id is UNIQUE and two products may share a slug stem across
    categories.
    """
    stem = re.sub(r"[^A-Z0-9]", "", slug.upper())[:16] or "PROD"
    return f"{stem}-{secrets.token_hex(3).upper()}"


def create_product(db, actor, payload: dict):
    """Create a product in draft. Nothing is published by this call."""
    slug = (payload.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="slug must be lowercase letters, digits and single hyphens",
        )

    category = db.get(Category, payload["category_id"])
    if category is None or category.level != 2:
        # products.category_level is GENERATED ALWAYS AS 2 with a composite FK,
        # so a level-1 category fails as an unreadable FK violation otherwise.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="products attach to level-2 categories only",
        )

    if db.execute(select(Product.id).where(Product.slug == slug)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slug already in use"
        )

    product = Product(
        item_group_id=payload.get("item_group_id") or _generate_item_group_id(slug),
        slug=slug,
        title=payload["title"].strip(),
        description=payload.get("description"),
        brand=payload.get("brand") or "Pixi",
        category_id=category.id,
        tags=payload.get("tags") or [],
        condition=payload.get("condition") or "new",
        gender=payload.get("gender"),
        age_group=payload.get("age_group"),
        status="draft",
    )
    db.add(product)
    db.flush()
    return product
```

Add `from models.products import Product` and `from sqlalchemy import select` to the existing imports if not already present (`select` and `Product` are already imported by `list_products_for_admin`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the Pydantic contract and the route**

```python
# backend/schema/admin_catalog.py  — append

from pydantic import BaseModel, Field


class admin_product_create(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    brand: str = Field(default="Pixi", max_length=128)
    category_id: int
    description: str | None = None
    tags: list[str] = []
    condition: str = "new"
    gender: str | None = None
    age_group: str | None = None
    item_group_id: str | None = None


class admin_product_detail(BaseModel):
    id: int
    item_group_id: str
    slug: str
    title: str
    brand: str
    status: str
    category_id: int
```

```python
# backend/routes/admin_catalog.py  — append

from fastapi import status as http_status

from repositories.admin_catalog import create_product
from schema.admin_catalog import admin_product_create, admin_product_detail


@router.post(
    "/products",
    response_model=admin_product_detail,
    status_code=http_status.HTTP_201_CREATED,
)
def admin_create_product(
    payload: admin_product_create,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create a product in draft. Publishing is a separate, validated step."""
    product = create_product(db, actor, payload.model_dump(exclude_none=False))
    db.commit()
    db.refresh(product)
    return product
```

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS, 66 tests.

- [ ] **Step 7: Commit**

```bash
git add backend/schema/admin_catalog.py backend/repositories/admin_catalog.py \
        backend/routes/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: create a product in draft"
```

---

### Task 2: Slug normalization and the redirect writer

**Files:**
- Create: `backend/repositories/admin_slugs.py`
- Test: `backend/tests/test_admin_slugs.py`

**Interfaces:**
- Produces: `normalize_translation_slug(raw: str) -> str`; `record_slug_change(db, *, locale: str, old_slug: str, product_id: int, actor_id: int | None) -> None`.

**Why its own module:** the Arabic rules are subtle, and this is used by product, category and collection renames later. The redirect is **entity-targeted, not path-targeted** — `models/url_redirects.py` documents why: storing `entity_id` means renaming A→B→C resolves in one hop, where a literal `to_path` would build a chain.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_slugs.py
"""Slug rules and rename redirects.

Migration 0003 made the translation slug CHECK a *denylist* because
"[[:alnum:]]" is ASCII-only under COLLATE "C" and rejected every Arabic slug.
These tests defend that: Arabic must survive normalization intact.
"""

import pytest

from repositories.admin_slugs import normalize_translation_slug


def test_arabic_slug_survives_normalization():
    assert normalize_translation_slug("صندل جلد") == "صندل-جلد"


def test_spaces_become_single_hyphens():
    assert normalize_translation_slug("  suede   sandal  ") == "suede-sandal"


def test_uppercase_is_lowered():
    assert normalize_translation_slug("Suede Sandal") == "suede-sandal"


def test_punctuation_is_stripped():
    assert normalize_translation_slug("suede/sandal!") == "suedesandal"


def test_invisible_characters_are_removed():
    """Tatweel and the bidi marks are in the CHECK's denylist."""
    assert normalize_translation_slug("صنـ__TATWEEL__دل".replace("__TATWEEL__", "ـ")) == "صندل"


def test_blank_slug_is_rejected():
    with pytest.raises(ValueError):
        normalize_translation_slug("   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_slugs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repositories.admin_slugs'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_slugs.py
"""Slug normalization and rename redirects.

The translation slug CHECK is a denylist, not an allowlist (migration 0003):
under COLLATE "C" the POSIX class [[:alnum:]] is ASCII-only, so an allowlist
rejects every Arabic slug. Normalization here mirrors that denylist exactly —
anything the constraint forbids is removed before the value reaches the column.
"""

import re
import unicodedata

from models.url_redirects import UrlRedirect

# Exactly the characters ck_*_slug_no_invisibles forbids.
_INVISIBLES = "".join(
    chr(c) for c in (0x0640, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
                     0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                     0x2066, 0x2067, 0x2068, 0x2069)
)
_PUNCT = re.compile(r"""[!"#$%&'()*+,./:;<=>?@\[\\\]^`{|}~]""")


def normalize_translation_slug(raw: str) -> str:
    """Fold a human-typed title into a slug the CHECK constraint accepts.

    Arabic text is preserved as real Arabic — the locked decision is that slugs
    are stored decoded and percent-encoded exactly once at render.
    """
    text = unicodedata.normalize("NFC", raw or "")
    text = text.translate({ord(c): None for c in _INVISIBLES})
    text = _PUNCT.sub("", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-").lower()
    if not text:
        raise ValueError("slug is empty after normalization")
    return text


def fold_path(path: str) -> str:
    """The comparison form stored in url_redirects.from_path_fold."""
    return unicodedata.normalize("NFC", path).lower()


def record_slug_change(
    db, *, locale: str, old_slug: str, product_id: int, actor_id: int | None
) -> None:
    """Write a 301 from the retired path.

    Entity-targeted rather than path-targeted: resolution is
    old path -> entity -> that entity's *current* slug, so renaming A->B->C
    still yields exactly one hop instead of a chain. ck_url_redirects_single_target
    requires exactly one of entity_id / to_path, so to_path stays NULL.
    """
    from_path = f"/{locale}/products/{old_slug}"
    db.add(
        UrlRedirect(
            locale=locale,
            from_path=from_path,
            from_path_fold=fold_path(from_path),
            entity_type="product",
            entity_id=product_id,
            to_path=None,
            status_code=301,
            reason="slug_change",
            is_active=True,
            created_by_user_id=actor_id,
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_slugs.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/admin_slugs.py backend/tests/test_admin_slugs.py
git commit -m "Admin: slug normalization and entity-targeted rename redirects"
```

---

### Task 3: Upsert a translation

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Consumes: `normalize_translation_slug`, `record_slug_change` from Task 2; `create_product` from Task 1.
- Produces: `upsert_translation(db, actor, product_id: int, locale: str, payload: dict) -> ProductTranslation`. Route `PUT /api/admin/products/{id}/translations/{locale}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from models.locales import Locale
from models.url_redirects import UrlRedirect
from repositories.admin_catalog import upsert_translation
from sqlalchemy import select


def _locale(db, code: str) -> None:
    if db.get(Locale, code) is None:
        db.add(Locale(
            code=code, hreflang=code, name_native=code,
            text_direction="rtl" if code == "ar" else "ltr",
            is_default=(code == "en"), is_active=True, sort_order=1,
        ))
        db.flush()


def test_translation_is_created_unpublished_and_incomplete(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    assert tr.is_published is False
    assert tr.is_complete is False   # description + meta_description missing


def test_translation_becomes_complete_when_all_publishable_fields_are_present(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-2", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "وصف قصير",
    })

    assert tr.is_complete is True


def test_slug_defaults_to_the_normalized_title(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-3", "brand": "Pixi", "category_id": cat.id,
    })

    tr = upsert_translation(db, actor, p.id, "ar", {"title": "صندل جلد"})

    assert tr.slug == "صندل-جلد"


def test_renaming_a_published_slug_writes_a_301(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-4", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
        "slug": "صندل", "is_published": True,
    })

    upsert_translation(db, actor, p.id, "ar", {"slug": "صندل-جديد"})

    redirect = db.execute(
        select(UrlRedirect).where(UrlRedirect.entity_id == p.id)
    ).scalar_one()
    assert redirect.from_path == "/ar/products/صندل"
    assert redirect.status_code == 301


def test_renaming_an_unpublished_slug_writes_no_redirect(db):
    """Nothing has indexed a draft, so a redirect would be noise."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "tr-sandal-5", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل", "slug": "صندل-قديم"})

    upsert_translation(db, actor, p.id, "ar", {"slug": "صندل-اخر"})

    assert db.execute(
        select(UrlRedirect).where(UrlRedirect.entity_id == p.id)
    ).first() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'upsert_translation'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

from models.product_translations import ProductTranslation
from repositories.admin_slugs import normalize_translation_slug, record_slug_change
from services import cache

# ck_product_translations_published_requires_content
_PUBLISHABLE_FIELDS = ("title", "description", "meta_description")


def upsert_translation(db, actor, product_id: int, locale: str, payload: dict):
    """Create or update one locale's content. Publishing is per-language.

    is_complete is derived, never taken from the caller: it means "has every
    field the publish CHECK requires", so the operator's readiness view cannot
    disagree with what the database will actually accept.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one_or_none()

    is_new = tr is None
    if is_new:
        tr = ProductTranslation(
            product_id=product_id, locale=locale,
            translation_source="human", is_published=False, is_complete=False,
        )
        db.add(tr)

    old_slug = None if is_new else tr.slug
    was_published = False if is_new else tr.is_published

    for field in ("title", "description", "seo_title", "meta_description",
                  "og_title", "og_description", "og_image_url", "image_alt"):
        if field in payload:
            setattr(tr, field, payload[field])

    if payload.get("slug"):
        tr.slug = normalize_translation_slug(payload["slug"])
    elif is_new:
        tr.slug = normalize_translation_slug(payload.get("title") or product.slug)

    if "is_published" in payload:
        tr.is_published = bool(payload["is_published"])

    tr.is_complete = all(getattr(tr, f, None) for f in _PUBLISHABLE_FIELDS)
    db.flush()

    # A draft has never been indexed, so a redirect from it would be noise.
    if was_published and old_slug and old_slug != tr.slug:
        record_slug_change(
            db, locale=locale, old_slug=old_slug,
            product_id=product_id, actor_id=actor.id,
        )
        db.flush()

    _invalidate(db, product_id)
    return tr


def _invalidate(db, product_id: int) -> None:
    """Drop every cached copy of this product, in every locale it has.

    invalidate_product's docstring is explicit that a missing locale leaves that
    locale serving stale content, so the map is read from the rows rather than
    assumed.
    """
    slugs = {
        loc: slug
        for loc, slug in db.execute(
            select(ProductTranslation.locale, ProductTranslation.slug).where(
                ProductTranslation.product_id == product_id
            )
        ).all()
    }
    cache.invalidate_product(product_id, slugs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Add the route**

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import upsert_translation
from schema.admin_catalog import admin_translation_upsert, admin_translation_detail


@router.put(
    "/products/{product_id}/translations/{locale}",
    response_model=admin_translation_detail,
)
def admin_upsert_translation(
    product_id: int,
    locale: str,
    payload: admin_translation_upsert,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create or replace one language's content for a product."""
    tr = upsert_translation(
        db, actor, product_id, locale,
        payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(tr)
    return tr
```

```python
# backend/schema/admin_catalog.py  — append

class admin_translation_upsert(BaseModel):
    title: str | None = None
    description: str | None = None
    slug: str | None = None
    seo_title: str | None = None
    meta_description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
    image_alt: str | None = None
    is_published: bool | None = None


class admin_translation_detail(BaseModel):
    locale: str
    title: str | None
    description: str | None
    slug: str
    meta_description: str | None
    is_published: bool
    is_complete: bool
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 75 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: per-language translation upsert with rename redirects"
```

---

### Task 4: Generate the variant matrix

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Produces: `generate_variants(db, actor, product_id: int, sizes: list[str], colors: list[str], defaults: dict) -> list[ProductVariant]`. Route `POST /api/admin/products/{id}/variants`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from repositories.admin_catalog import generate_variants


def test_matrix_creates_one_variant_per_size_and_colour(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(
        db, actor, p.id, ["38", "39"], ["black", "tan"], {"price": "500.00"}
    )

    assert len(variants) == 4


def test_generated_skus_match_the_format_constraint(db):
    import re
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-2", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    assert re.match(r"^[A-Z0-9][A-Z0-9-]*$", variants[0].sku)


def test_first_generated_variant_becomes_the_default(db):
    """ck_products_active_has_default_variant blocks publishing without one."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-3", "brand": "Pixi", "category_id": cat.id,
    })

    variants = generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    db.refresh(p)
    assert p.default_variant_id == variants[0].id


def test_regenerating_an_existing_combination_is_skipped_not_duplicated(db):
    """UNIQUE(product_id, size, color, material) would otherwise raise."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-4", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})

    second = generate_variants(
        db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"}
    )

    assert len(second) == 1
    assert second[0].size == "39"


def test_sale_price_above_price_is_rejected(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "mx-sandal-5", "brand": "Pixi", "category_id": cat.id,
    })

    with pytest.raises(HTTPException) as exc:
        generate_variants(db, actor, p.id, ["38"], ["black"],
                          {"price": "500.00", "sale_price": "600.00"})

    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'generate_variants'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

from decimal import Decimal

from models.product_variants import ProductVariant


def _variant_sku(item_group_id: str, size: str, color: str) -> str:
    """Deterministic and constraint-shaped: ^[A-Z0-9][A-Z0-9-]*$."""
    parts = [item_group_id, size, color]
    cleaned = ["".join(ch for ch in p.upper() if ch.isalnum()) for p in parts]
    return "-".join(part for part in cleaned if part)


def generate_variants(db, actor, product_id: int, sizes, colors, defaults: dict):
    """Create the size x colour cross product, skipping combinations that exist.

    SKUs are generated because they are immutable once written
    (trg_variants_sku_immutable) — a typo would otherwise be permanent.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    price = Decimal(str(defaults.get("price", "0")))
    sale_price = defaults.get("sale_price")
    sale_price = Decimal(str(sale_price)) if sale_price is not None else None
    if sale_price is not None and sale_price > price:
        raise HTTPException(
            status_code=400, detail="sale price cannot exceed the price"
        )

    existing = {
        (v.size, v.color)
        for v in db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product_id)
        ).scalars()
    }

    created = []
    for size in sizes:
        for color in colors:
            if (size, color) in existing:
                continue
            variant = ProductVariant(
                product_id=product_id,
                sku=_variant_sku(product.item_group_id, size, color),
                variant_title=f"{size} / {color}",
                size=size,
                size_system=defaults.get("size_system"),
                color=color,
                material=defaults.get("material"),
                attributes={},
                price=price,
                sale_price=sale_price,
                currency="EGP",
                cost=None,  # COGS is admin-gated; set on the variant edit screen
                availability=defaults.get("availability", "in_stock"),
                stock_quantity=int(defaults.get("stock_quantity", 0)),
                merchant_eligible=True,
                is_active=True,
            )
            db.add(variant)
            created.append(variant)

    db.flush()

    if created and product.default_variant_id is None:
        product.default_variant_id = created[0].id
        db.flush()

    _invalidate(db, product_id)
    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (14 tests).

- [ ] **Step 5: Add the route**

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import generate_variants
from schema.admin_catalog import admin_variant_matrix, admin_variant_row


@router.post(
    "/products/{product_id}/variants",
    response_model=list[admin_variant_row],
    status_code=http_status.HTTP_201_CREATED,
)
def admin_generate_variants(
    product_id: int,
    payload: admin_variant_matrix,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Generate the size x colour matrix. Existing combinations are skipped."""
    created = generate_variants(
        db, actor, product_id, payload.sizes, payload.colors,
        payload.model_dump(exclude={"sizes", "colors"}, exclude_none=True),
    )
    db.commit()
    for v in created:
        db.refresh(v)
    return created
```

```python
# backend/schema/admin_catalog.py  — append

from decimal import Decimal


class admin_variant_matrix(BaseModel):
    sizes: list[str] = Field(min_length=1)
    colors: list[str] = Field(min_length=1)
    price: Decimal
    sale_price: Decimal | None = None
    stock_quantity: int = 0
    availability: str = "in_stock"
    size_system: str | None = None
    material: str | None = None


class admin_variant_row(BaseModel):
    id: int
    sku: str
    variant_title: str
    size: str | None
    color: str | None
    price: Decimal
    sale_price: Decimal | None
    stock_quantity: int
    is_active: bool
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 80 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: generate the size x colour variant matrix"
```

---

### Task 5: Publish with structured blockers

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Produces: `publish_readiness(db, product_id: int, locale: str) -> list[dict]` returning `[{"code": str, "message": str}]`; `publish_product(db, actor, product_id: int, locale: str) -> ProductTranslation`. Route `POST /api/admin/products/{id}/publish`.

**Why:** the database CHECK constraints will reject an unpublishable product with an unreadable `IntegrityError`. This returns what is missing, as data.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from repositories.admin_catalog import publish_product, publish_readiness


def test_readiness_reports_a_missing_variant(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-1", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "no_variant" in codes


def test_readiness_reports_missing_translation_content(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-2", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    codes = {b["code"] for b in publish_readiness(db, p.id, "ar")}

    assert "incomplete_translation" in codes


def test_a_ready_product_publishes_and_goes_active(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-3", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })

    tr = publish_product(db, actor, p.id, "ar")

    db.refresh(p)
    assert tr.is_published is True
    assert p.status == "active"


def test_publishing_an_unready_product_raises_422_with_blockers(db):
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-4", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})

    with pytest.raises(HTTPException) as exc:
        publish_product(db, actor, p.id, "ar")

    assert exc.value.status_code == 422
    assert isinstance(exc.value.detail, list)
    assert {b["code"] for b in exc.value.detail} >= {"no_variant", "incomplete_translation"}


def test_publishing_one_language_leaves_the_other_unpublished(db):
    """Per-language publishing is the whole point of the draft flow."""
    _locale(db, "ar")
    _locale(db, "en")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "pub-5", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })
    upsert_translation(db, actor, p.id, "en", {"title": "Sandal"})

    publish_product(db, actor, p.id, "ar")

    en = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == p.id, ProductTranslation.locale == "en"
        )
    ).scalar_one()
    assert en.is_published is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'publish_readiness'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

def publish_readiness(db, product_id: int, locale: str) -> list[dict]:
    """What still blocks this language from publishing, as data.

    Mirrors the database CHECK constraints deliberately. The constraints remain
    the authority — this exists so the operator sees a sentence instead of an
    IntegrityError.
    """
    blockers: list[dict] = []

    variant_count = db.execute(
        select(func.count()).select_from(ProductVariant).where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
    ).scalar_one()
    if variant_count == 0:
        blockers.append({
            "code": "no_variant",
            "message": "Add at least one variant before publishing.",
        })

    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one_or_none()

    if tr is None:
        blockers.append({
            "code": "no_translation",
            "message": f"No {locale} content exists yet.",
        })
    else:
        missing = [f for f in _PUBLISHABLE_FIELDS if not getattr(tr, f, None)]
        if missing:
            blockers.append({
                "code": "incomplete_translation",
                "message": (
                    f"{locale} needs: " + ", ".join(m.replace('_', ' ') for m in missing)
                ),
            })

    return blockers


def publish_product(db, actor, product_id: int, locale: str):
    """Publish one language, activating the product if it was still a draft."""
    blockers = publish_readiness(db, product_id, locale)
    if blockers:
        raise HTTPException(status_code=422, detail=blockers)

    product = db.get(Product, product_id)
    tr = db.execute(
        select(ProductTranslation).where(
            ProductTranslation.product_id == product_id,
            ProductTranslation.locale == locale,
        )
    ).scalar_one()

    tr.is_published = True
    tr.is_complete = True
    if product.status != "active":
        product.status = "active"

    db.flush()
    _invalidate(db, product_id)
    return tr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (19 tests).

- [ ] **Step 5: Add the route**

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import publish_product, publish_readiness
from schema.admin_catalog import admin_blocker, admin_translation_detail


@router.get("/products/{product_id}/readiness", response_model=list[admin_blocker])
def admin_publish_readiness(
    product_id: int,
    locale: str = Query(..., min_length=2, max_length=5),
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """What still blocks this language from publishing. Empty list means ready."""
    return publish_readiness(db, product_id, locale)


@router.post("/products/{product_id}/publish", response_model=admin_translation_detail)
def admin_publish(
    product_id: int,
    locale: str = Query(..., min_length=2, max_length=5),
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Publish one language. Returns 422 with a blocker list if not ready."""
    tr = publish_product(db, actor, product_id, locale)
    db.commit()
    db.refresh(tr)
    return tr
```

```python
# backend/schema/admin_catalog.py  — append

class admin_blocker(BaseModel):
    code: str
    message: str
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 85 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: per-language publish with structured blockers"
```

---

### Task 6: Prove cache invalidation actually invalidates

**Files:**
- Test: `backend/tests/test_admin_cache.py` (create)
- Modify: `backend/scripts/check_cache_live.py` (extend)

**Interfaces:**
- Consumes: everything from Tasks 1, 3, 4, 5.

**Why this is its own task:** §5 of the handoff records that this project's first cache invalidation was a **silent no-op** — `INCR` on a missing key yields 1 and the default was already 1. It was invisible with Redis down (all misses) and invisible with Redis up unless the test asserted the value *changed*. Asserting the code ran is not enough.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_cache.py
"""Admin writes must actually invalidate, not merely call the invalidator.

The first cache invalidation in this project was a no-op: INCR on a missing key
returns 1, and the default version was already 1. Nothing failed. These tests
assert the version *moved*.
"""

from services import cache


def test_publishing_bumps_the_listing_version(db, monkeypatch):
    from repositories.admin_catalog import (
        create_product, generate_variants, publish_product,
    )
    from tests.test_admin_writes import _actor, _level2_category, _locale

    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    product = create_product(db, actor, {
        "title": "Cache", "slug": "cache-probe", "brand": "Pixi",
        "category_id": cat.id,
    })
    generate_variants(db, actor, product.id, ["38"], ["black"], {"price": "500.00"})

    from repositories.admin_catalog import upsert_translation
    upsert_translation(db, actor, product.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })

    before = cache.namespace_version(cache.NS_LISTING)
    publish_product(db, actor, product.id, "ar")
    after = cache.namespace_version(cache.NS_LISTING)

    assert after != before, "listing cache version did not move — invalidation is a no-op"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_cache.py -q`
Expected: FAIL if `_invalidate` is not wired into `publish_product`; PASS once it is. If it passes immediately, temporarily comment out the `_invalidate(db, product_id)` call in `publish_product`, re-run to confirm the test catches it, then restore.

- [ ] **Step 3: Confirm every write path invalidates**

Verify `_invalidate(db, product_id)` is called at the end of `upsert_translation`, `generate_variants` and `publish_product`. `create_product` does not need it — a brand-new draft has never been cached.

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 86 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_admin_cache.py
git commit -m "Admin: assert cache invalidation moves the version"
```

---

### Task 7: End-to-end HTTP walkthrough

**Files:**
- Modify: `backend/tests/test_admin_catalog.py`

**Interfaces:**
- Consumes: the `staff_token` fixture already in `test_admin_catalog.py`, and every route from Tasks 1–5.

**Why:** the repository tests prove the rules; this proves the routes are wired, committed and reachable — the failure mode unit tests cannot see.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_catalog.py  — append

def test_operator_can_take_a_product_from_nothing_to_published(client, staff_token):
    """The whole point of this slice: a shop operator, not a developer."""
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}

    categories = client.get("/api/admin/products", headers=auth)
    assert categories.status_code == 200

    created = client.post("/api/admin/products", headers=auth, json={
        "title": "E2E Sandal", "slug": "e2e-sandal", "brand": "Pixi",
        "category_id": _any_level2_category_id(),
    })
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]

    variants = client.post(
        f"/api/admin/products/{product_id}/variants", headers=auth,
        json={"sizes": ["38", "39"], "colors": ["black"], "price": "500.00",
              "stock_quantity": 5},
    )
    assert variants.status_code == 201
    assert len(variants.json()) == 2

    not_ready = client.post(
        f"/api/admin/products/{product_id}/publish?locale=ar", headers=auth
    )
    assert not_ready.status_code == 422
    assert any(b["code"] == "no_translation" for b in not_ready.json()["detail"])

    client.put(
        f"/api/admin/products/{product_id}/translations/ar", headers=auth,
        json={"title": "صندل", "description": "وصف", "meta_description": "قصير"},
    )

    published = client.post(
        f"/api/admin/products/{product_id}/publish?locale=ar", headers=auth
    )
    assert published.status_code == 200
    assert published.json()["is_published"] is True
```

Add this helper above the test:

```python
def _any_level2_category_id() -> int:
    """Seed data provides level-2 categories; this test needs one that exists."""
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.categories import Category

    db = SessionLocal()
    try:
        return db.execute(
            select(Category.id).where(Category.level == 2).order_by(Category.id).limit(1)
        ).scalar_one()
    finally:
        db.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_catalog.py -q`
Expected: FAIL until every route from Tasks 1–5 exists.

- [ ] **Step 3: Ensure seed data has a level-2 category**

Run: `.venv\Scripts\python.exe scripts/seed.py` if the query in the helper raises `NoResultFound`.

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 87 tests.

- [ ] **Step 5: Clean up committed test data**

This test commits a real product, and `products.slug` is `UNIQUE` — a leaked row makes the second run fail with 409. Add this fixture to `test_admin_catalog.py` and take `e2e_cleanup` as an argument in the test above:

```python
@pytest.fixture
def e2e_cleanup():
    """Remove the product this test commits, so the suite is repeatable."""
    slugs: list[str] = []
    yield slugs

    from sqlalchemy import select

    from models.product_translations import ProductTranslation
    from models.product_variants import ProductVariant
    from models.products import Product

    db = SessionLocal()
    try:
        for slug in slugs:
            product = db.execute(
                select(Product).where(Product.slug == slug)
            ).scalar_one_or_none()
            if product is None:
                continue
            # default_variant_id references a variant, so clear it before the
            # variants are removed or the FK blocks the delete.
            product.default_variant_id = None
            db.flush()
            for model in (ProductTranslation, ProductVariant):
                for row in db.execute(
                    select(model).where(model.product_id == product.id)
                ).scalars():
                    db.delete(row)
            db.delete(product)
        db.commit()
    finally:
        db.close()
```

Register the slug at the start of the test body, immediately after creating it:

```python
    e2e_cleanup.append("e2e-sandal")
```

Then run the suite twice to confirm repeatability:

Run: `.venv\Scripts\python.exe -m pytest tests -q; .venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS both times, identical counts.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_admin_catalog.py
git commit -m "Admin: end-to-end draft to published walkthrough"
```

---

### Task 8: Load one product for the editor

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Consumes: `create_product` (Task 1), `upsert_translation` (Task 3), `generate_variants` (Task 4), `_invalidate` (Task 3).
- Produces: `get_product_for_admin(db, product_id: int) -> dict`. Route `GET /api/admin/products/{id}`.

**Why:** the editor screen cannot load a product to edit. `GET /products/{slug}` is public and filters to active + published, so it cannot see the draft the operator is working on.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from repositories.admin_catalog import get_product_for_admin


def test_editor_load_returns_every_locale_including_unpublished(db):
    _locale(db, "ar")
    _locale(db, "en")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "load-1", "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, p.id, "ar", {"title": "صندل"})
    upsert_translation(db, actor, p.id, "en", {"title": "Sandal"})

    loaded = get_product_for_admin(db, p.id)

    assert {t["locale"] for t in loaded["translations"]} == {"ar", "en"}
    assert all(t["is_published"] is False for t in loaded["translations"])


def test_editor_load_includes_variants(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Sandal", "slug": "load-2", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38", "39"], ["black"], {"price": "500.00"})

    loaded = get_product_for_admin(db, p.id)

    assert len(loaded["variants"]) == 2


def test_editor_load_of_a_missing_product_is_404(db):
    with pytest.raises(HTTPException) as exc:
        get_product_for_admin(db, 10**9)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_product_for_admin'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

def get_product_for_admin(db, product_id: int) -> dict:
    """Everything the editor needs, regardless of publish state.

    Three queries — the product, its translations, its variants — so the shape
    stays constant as a product gains variants.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    translations = [
        {
            "locale": t.locale,
            "title": t.title,
            "description": t.description,
            "slug": t.slug,
            "meta_description": t.meta_description,
            "is_published": t.is_published,
            "is_complete": t.is_complete,
        }
        for t in db.execute(
            select(ProductTranslation)
            .where(ProductTranslation.product_id == product_id)
            .order_by(ProductTranslation.locale)
        ).scalars()
    ]

    variants = [
        {
            "id": v.id,
            "sku": v.sku,
            "variant_title": v.variant_title,
            "size": v.size,
            "color": v.color,
            "price": v.price,
            "sale_price": v.sale_price,
            "stock_quantity": v.stock_quantity,
            "is_active": v.is_active,
        }
        for v in db.execute(
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.id)
        ).scalars()
    ]

    return {
        "id": product.id,
        "item_group_id": product.item_group_id,
        "slug": product.slug,
        "title": product.title,
        "brand": product.brand,
        "status": product.status.value if hasattr(product.status, "value") else product.status,
        "category_id": product.category_id,
        "translations": translations,
        "variants": variants,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (22 tests).

- [ ] **Step 5: Add the schema and route**

```python
# backend/schema/admin_catalog.py  — append

class admin_product_full(BaseModel):
    id: int
    item_group_id: str
    slug: str
    title: str
    brand: str
    status: str
    category_id: int
    translations: list[admin_translation_detail]
    variants: list[admin_variant_row]
```

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import get_product_for_admin
from schema.admin_catalog import admin_product_full


@router.get("/products/{product_id}", response_model=admin_product_full)
def admin_get_product(
    product_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Load a product for editing, drafts and unpublished languages included."""
    return get_product_for_admin(db, product_id)
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 90 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: load a product for editing"
```

---

### Task 9: Edit base fields and archive

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Produces: `update_product(db, actor, product_id: int, payload: dict) -> Product`. Routes `PATCH /api/admin/products/{id}` and `POST /api/admin/products/{id}/archive`.

**Why:** spec §5.5 — never hard-delete. `fk_order_items_product_id` is `ON DELETE RESTRICT`, so anything sold cannot be removed anyway; archiving is the supported path.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from repositories.admin_catalog import archive_product, update_product


def test_base_fields_can_be_edited(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "Old", "slug": "edit-1", "brand": "Pixi", "category_id": cat.id,
    })

    updated = update_product(db, actor, p.id, {"title": "New", "brand": "Pixi"})

    assert updated.title == "New"


def test_base_slug_must_stay_ascii(db):
    """products.slug has an ASCII allowlist; only translation slugs take Arabic."""
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-2", "brand": "Pixi", "category_id": cat.id,
    })

    with pytest.raises(HTTPException) as exc:
        update_product(db, actor, p.id, {"slug": "صندل"})

    assert exc.value.status_code == 400


def test_archiving_leaves_the_row_in_place(db):
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-3", "brand": "Pixi", "category_id": cat.id,
    })

    archive_product(db, actor, p.id)

    db.refresh(p)
    assert p.status == "archived"
    assert db.get(Product, p.id) is not None


def test_archiving_unpublishes_every_language(db):
    """An archived product must stop being served, in both locales."""
    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    p = create_product(db, actor, {
        "title": "X", "slug": "edit-4", "brand": "Pixi", "category_id": cat.id,
    })
    generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})
    upsert_translation(db, actor, p.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })
    publish_product(db, actor, p.id, "ar")

    archive_product(db, actor, p.id)

    tr = db.execute(
        select(ProductTranslation).where(ProductTranslation.product_id == p.id)
    ).scalar_one()
    assert tr.is_published is False
```

Add `from models.products import Product` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'archive_product'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

_EDITABLE_BASE_FIELDS = (
    "title", "description", "brand", "tags",
    "condition", "gender", "age_group",
)


def update_product(db, actor, product_id: int, payload: dict):
    """Edit base (non-translated) fields. Status changes go through publish/archive."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    if "slug" in payload and payload["slug"] != product.slug:
        slug = (payload["slug"] or "").strip().lower()
        if not _SLUG_RE.match(slug):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="base slug must be ASCII lowercase, digits and single hyphens",
            )
        if db.execute(
            select(Product.id).where(Product.slug == slug, Product.id != product_id)
        ).first():
            raise HTTPException(status_code=409, detail="slug already in use")
        product.slug = slug

    if "category_id" in payload:
        category = db.get(Category, payload["category_id"])
        if category is None or category.level != 2:
            raise HTTPException(
                status_code=400, detail="products attach to level-2 categories only"
            )
        product.category_id = category.id

    for field in _EDITABLE_BASE_FIELDS:
        if field in payload:
            setattr(product, field, payload[field])

    db.flush()
    _invalidate(db, product_id)
    return product


def archive_product(db, actor, product_id: int):
    """Retire a product without deleting it.

    fk_order_items_product_id is ON DELETE RESTRICT, so anything sold cannot be
    deleted at all — and deleting would orphan the history GA4, Merchant Center
    and the Meta catalog key on. Every language is unpublished so the storefront
    stops serving it in both locales.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    for tr in db.execute(
        select(ProductTranslation).where(ProductTranslation.product_id == product_id)
    ).scalars():
        tr.is_published = False

    product.status = "archived"
    db.flush()
    _invalidate(db, product_id)
    return product
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (26 tests).

- [ ] **Step 5: Add the schema and routes**

```python
# backend/schema/admin_catalog.py  — append

class admin_product_update(BaseModel):
    title: str | None = None
    slug: str | None = None
    brand: str | None = None
    category_id: int | None = None
    description: str | None = None
    tags: list[str] | None = None
    condition: str | None = None
    gender: str | None = None
    age_group: str | None = None
```

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import archive_product, update_product
from schema.admin_catalog import admin_product_update


@router.patch("/products/{product_id}", response_model=admin_product_detail)
def admin_update_product(
    product_id: int,
    payload: admin_product_update,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Edit base fields. Only fields actually sent are changed."""
    product = update_product(
        db, actor, product_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/archive", response_model=admin_product_detail)
def admin_archive_product(
    product_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Retire a product. Never deletes — sold products cannot be deleted at all."""
    product = archive_product(db, actor, product_id)
    db.commit()
    db.refresh(product)
    return product
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 94 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: edit base fields and archive instead of deleting"
```

---

### Task 10: Edit a variant, with COGS behind the admin gate

**Files:**
- Modify: `backend/repositories/admin_catalog.py`, `backend/schema/admin_catalog.py`, `backend/routes/admin_catalog.py`
- Test: `backend/tests/test_admin_writes.py`

**Interfaces:**
- Consumes: `require_staff` semantics — the caller's `actor` is the resolved `User`.
- Produces: `update_variant(db, actor, variant_id: int, payload: dict) -> ProductVariant`. Route `PATCH /api/admin/variants/{id}`.

**Why COGS is special (spec §3):** `product_variants.cost` feeds `order_items.unit_cogs` at order creation and therefore `contribution_profit`. It is a money field, not a catalog field, so `catalog` (2) may set price and stock but only `admin` (4) may set cost.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_admin_writes.py  — append

from decimal import Decimal

from repositories.admin_catalog import update_variant


def _variant(db, actor, slug: str):
    cat = _level2_category(db)
    p = create_product(db, actor, {
        "title": "V", "slug": slug, "brand": "Pixi", "category_id": cat.id,
    })
    return generate_variants(db, actor, p.id, ["38"], ["black"], {"price": "500.00"})[0]


def test_catalog_role_can_change_price_and_stock(db):
    actor = _actor(db)
    v = _variant(db, actor, "var-1")

    updated = update_variant(db, actor, v.id, {"price": "450.00", "stock_quantity": 9})

    assert updated.price == Decimal("450.00")
    assert updated.stock_quantity == 9


def test_catalog_role_cannot_set_cogs(db):
    actor = _actor(db)             # role="catalog"
    v = _variant(db, actor, "var-2")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"cost": "200.00"})

    assert exc.value.status_code == 403


def test_admin_role_can_set_cogs(db):
    admin = User(
        email="cogs-admin@example.com", password_hash="x",
        full_name="Admin", role="admin", is_active=True,
    )
    db.add(admin)
    db.flush()
    v = _variant(db, admin, "var-3")

    updated = update_variant(db, admin, v.id, {"cost": "200.00"})

    assert updated.cost == Decimal("200.00")


def test_sale_price_above_price_is_rejected_on_update(db):
    actor = _actor(db)
    v = _variant(db, actor, "var-4")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"sale_price": "900.00"})

    assert exc.value.status_code == 400


def test_sku_cannot_be_changed(db):
    """trg_variants_sku_immutable enforces it; the API refuses before it fires."""
    actor = _actor(db)
    v = _variant(db, actor, "var-5")

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, v.id, {"sku": "REWRITTEN-1"})

    assert exc.value.status_code == 400
    assert "immutable" in exc.value.detail.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: FAIL — `ImportError: cannot import name 'update_variant'`.

- [ ] **Step 3: Implement**

```python
# backend/repositories/admin_catalog.py  — append

from services.role_access_level import LEVEL_ADMIN, set_access_level

_EDITABLE_VARIANT_FIELDS = (
    "variant_title", "gtin", "mpn", "material", "size_system",
    "availability", "stock_quantity", "weight_grams",
    "length_cm", "width_cm", "height_cm", "merchant_eligible", "is_active",
)


def update_variant(db, actor, variant_id: int, payload: dict):
    """Edit a variant. SKU is refused; COGS requires an admin."""
    variant = db.get(ProductVariant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="variant not found")

    if "sku" in payload and payload["sku"] != variant.sku:
        # trg_variants_sku_immutable would raise a restrict_violation. Refusing
        # here gives the operator a sentence instead of a database error.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKU is immutable — Merchant Center and the Meta catalog key on it",
        )

    if "cost" in payload:
        if set_access_level(actor) < LEVEL_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="COGS may only be set by an admin",
            )
        variant.cost = Decimal(str(payload["cost"]))

    price = Decimal(str(payload["price"])) if "price" in payload else variant.price
    if "sale_price" in payload:
        sale_price = payload["sale_price"]
        sale_price = Decimal(str(sale_price)) if sale_price is not None else None
    else:
        sale_price = variant.sale_price

    if sale_price is not None and sale_price > price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sale price cannot exceed the price",
        )

    variant.price = price
    variant.sale_price = sale_price

    for field in _EDITABLE_VARIANT_FIELDS:
        if field in payload:
            setattr(variant, field, payload[field])

    db.flush()
    _invalidate(db, variant.product_id)
    return variant
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_admin_writes.py -q`
Expected: PASS (31 tests).

- [ ] **Step 5: Add the schema and route**

```python
# backend/schema/admin_catalog.py  — append

class admin_variant_update(BaseModel):
    variant_title: str | None = None
    price: Decimal | None = None
    sale_price: Decimal | None = None
    cost: Decimal | None = None
    stock_quantity: int | None = None
    availability: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    material: str | None = None
    size_system: str | None = None
    weight_grams: int | None = None
    merchant_eligible: bool | None = None
    is_active: bool | None = None
```

```python
# backend/routes/admin_catalog.py  — append

from repositories.admin_catalog import update_variant
from schema.admin_catalog import admin_variant_update


@router.patch("/variants/{variant_id}", response_model=admin_variant_row)
def admin_update_variant(
    variant_id: int,
    payload: admin_variant_update,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Edit one variant. Setting `cost` additionally requires an admin."""
    variant = update_variant(
        db, actor, variant_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(variant)
    return variant
```

Note the route gate stays `LEVEL_CATALOG`: the COGS check happens inside `update_variant`, because whether admin is required depends on *which field* was sent, not on the endpoint.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest tests -q` — Expected: PASS, 99 tests.

```bash
git add backend/repositories/admin_catalog.py backend/routes/admin_catalog.py \
        backend/schema/admin_catalog.py backend/tests/test_admin_writes.py
git commit -m "Admin: edit variants, with COGS behind the admin gate"
```

---

## Done when

- `.venv\Scripts\python.exe -m pytest tests -q` passes, twice in a row
- `.venv\Scripts\python.exe scripts/verify_triggers.py` still reports all checks passed
- `.venv\Scripts\python.exe scripts/check_query_count.py` still within budget
- An operator can create, fill, and publish a product using only HTTP calls
- `README.md` "Status" row for S1 updated with the new test count
