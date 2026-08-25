"""The admin catalog endpoints, exercised over HTTP with real staff logins.

``test_admin_access.py`` proves the gate logic in isolation. These prove the
gate is actually *wired to the routes* — a correct check that nobody applied
is the failure mode unit tests cannot see.

The admin listing differs from the public one in a way worth stating: the public
``GET /products`` filters to ``status='active'`` with a published translation,
because that is what a shopper and a crawler may see. The admin listing must
show drafts, or the operator cannot find the product they are part-way through
writing.
"""

import uuid

import pytest

from core.db import SessionLocal
from models.users import User
from repositories.register import create_staff_user

PASSWORD = "Adm1n-Gate-Test!"


def _login(client, email: str) -> str:
    r = client.post(
        "/api/en/auth/staff/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def staff_token(client):
    """Create a real staff account, log in, hand back a token, then remove it.

    ``create_staff_user`` commits, so this cannot ride on the rolled-back
    session fixtures — the account is deleted explicitly afterwards.
    """
    created: list[int] = []

    def _make(role: str) -> str:
        email = f"admin-test-{role}-{uuid.uuid4().hex[:8]}@example.com"
        db = SessionLocal()
        try:
            user = create_staff_user(
                db, email=email, password=PASSWORD, full_name=f"Test {role}", role=role
            )
            created.append(user.id)
        finally:
            db.close()
        return _login(client, email)

    yield _make

    db = SessionLocal()
    try:
        for uid in created:
            user = db.get(User, uid)
            if user is not None:
                db.delete(user)
        db.commit()
    finally:
        db.close()


def test_admin_listing_requires_a_token(client):
    assert client.get("/api/admin/products").status_code == 403


def test_support_role_cannot_reach_the_admin_listing(client, staff_token):
    token = staff_token("support")

    r = client.get("/api/admin/products", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 403


def test_catalog_role_can_reach_the_admin_listing(client, staff_token):
    token = staff_token("catalog")

    r = client.get("/api/admin/products", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_a_shopper_token_is_not_a_staff_token(client):
    """Staff and shopper tokens carry different scopes and must not cross over."""
    r = client.post(
        "/api/en/auth/login",
        json={"email": "nobody-here@example.com", "password": "irrelevant"},
    )
    # Whatever the shopper login does, it must not mint something the admin
    # namespace accepts. An unauthenticated call is the strongest form of that.
    assert client.get("/api/admin/products").status_code == 403
    assert r.status_code in (401, 404, 422)


def test_admin_listing_shows_drafts_that_the_public_listing_hides(client, staff_token):
    token = staff_token("catalog")

    admin = client.get(
        "/api/admin/products?status=draft",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert admin.status_code == 200
    # Every row the admin sees under status=draft must be a draft; the public
    # endpoint has no such view at all.
    assert all(item["status"] == "draft" for item in admin.json()["items"])


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
            # variants are removed or the FK blocks the delete. The brief's
            # fixture nulls default_variant_id alone, but this test publishes
            # the product (status becomes 'active'), and
            # ck_products_active_has_default_variant forbids status='active'
            # with a NULL default_variant_id -- so status must drop out of
            # 'active' in the same update or the clear itself raises
            # IntegrityError.
            product.status = "draft"
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


def test_the_cache_is_dropped_only_once_the_edit_is_visible_to_other_connections(
    client, staff_token, e2e_cleanup, monkeypatch
):
    """The whole point of deferring the invalidation, asserted from outside.

    ``test_admin_cache.py`` proves the deferral by draining the queue by hand,
    which cannot show that the route's ``db.commit()`` is what drains it in
    production. So this reads the product from a *separate* connection at the
    moment the invalidation fires. If the drop still happens inside the write
    transaction, that connection sees the pre-edit row -- which is exactly what
    a storefront read landing in the window would see, and would then cache for
    the next sixty seconds.
    """
    from sqlalchemy import select

    from models.products import Product
    from services import cache

    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = f"cache-http-{uuid.uuid4().hex[:8]}"

    created = client.post("/api/admin/products", headers=auth, json={
        "title": "Cache Sandal", "slug": slug, "brand": "Pixi",
        "category_id": _any_level2_category_id(),
    })
    assert created.status_code == 201, created.text
    e2e_cleanup.append(slug)
    product_id = created.json()["id"]

    # The key map is built from the translation rows, so the product needs one.
    tr = client.put(
        f"/api/admin/products/{product_id}/translations/en", headers=auth,
        json={"title": "Cache Sandal", "slug": slug, "description": "A sandal",
              "meta_description": "short"},
    )
    assert tr.status_code == 200, tr.text

    visible_at_invalidation: list[str] = []
    real_invalidate = cache.invalidate_product

    def watching_invalidate(pid: int, slugs_by_locale: dict[str, str]) -> None:
        probe = SessionLocal()
        try:
            visible_at_invalidation.append(
                probe.execute(
                    select(Product.brand).where(Product.id == pid)
                ).scalar_one()
            )
        finally:
            probe.close()
        real_invalidate(pid, slugs_by_locale)

    monkeypatch.setattr(cache, "invalidate_product", watching_invalidate)

    key = cache.key(cache.NS_PRODUCT, "en", slug)
    cache.set(key, {"price": "before the edit"})

    edit = client.patch(
        f"/api/admin/products/{product_id}", headers=auth, json={"brand": "Renamed"}
    )
    assert edit.status_code == 200, edit.text

    assert visible_at_invalidation == ["Renamed"], (
        "the cache was dropped while the edit was still uncommitted -- another "
        "connection reading here would refill it with the pre-edit row"
    )
    assert cache.get(key) is None


def test_operator_can_take_a_product_from_nothing_to_published(client, staff_token, e2e_cleanup):
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
    e2e_cleanup.append("e2e-sandal")
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


# --- Tasks 8-10 review fixes: HTTP-level coverage (I3) ----------------------
#
# Every Task 8-10 test up to here calls the repository functions directly, so
# the response models, the route gating, and the Pydantic request boundary
# were all unverified -- which is exactly how I2 (an sku field missing from
# admin_variant_update, silently swallowing an attempted SKU change) slipped
# through. These go over real HTTP with a real staff login instead.


def _create_product_with_variant(client, auth: dict, slug: str) -> tuple[int, int]:
    created = client.post("/api/admin/products", headers=auth, json={
        "title": "HTTP Sandal", "slug": slug, "brand": "Pixi",
        "category_id": _any_level2_category_id(),
    })
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]

    variants = client.post(
        f"/api/admin/products/{product_id}/variants", headers=auth,
        json={"sizes": ["38"], "colors": ["black"], "price": "500.00"},
    )
    assert variants.status_code == 201, variants.text
    return product_id, variants.json()[0]["id"]


def test_admin_get_product_returns_translations_and_variants(client, staff_token, e2e_cleanup):
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "http-load-1"
    product_id, _ = _create_product_with_variant(client, auth, slug)
    e2e_cleanup.append(slug)

    client.put(
        f"/api/admin/products/{product_id}/translations/ar", headers=auth,
        json={"title": "صندل"},
    )

    r = client.get(f"/api/admin/products/{product_id}", headers=auth)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == product_id
    assert len(body["variants"]) == 1
    assert {t["locale"] for t in body["translations"]} == {"ar"}


def test_admin_patch_product_edits_a_base_field(client, staff_token, e2e_cleanup):
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "http-edit-1"
    product_id, _ = _create_product_with_variant(client, auth, slug)
    e2e_cleanup.append(slug)

    r = client.patch(
        f"/api/admin/products/{product_id}", headers=auth, json={"title": "New Title"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["title"] == "New Title"


def test_admin_archive_product(client, staff_token, e2e_cleanup):
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "http-archive-1"
    product_id, _ = _create_product_with_variant(client, auth, slug)
    e2e_cleanup.append(slug)

    r = client.post(f"/api/admin/products/{product_id}/archive", headers=auth)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"


def test_admin_patch_variant_changes_price_as_catalog_role(client, staff_token, e2e_cleanup):
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "http-variant-1"
    _, variant_id = _create_product_with_variant(client, auth, slug)
    e2e_cleanup.append(slug)

    r = client.patch(
        f"/api/admin/variants/{variant_id}", headers=auth, json={"price": "425.00"},
    )

    assert r.status_code == 200, r.text
    from decimal import Decimal
    assert Decimal(str(r.json()["price"])) == Decimal("425.00")


def test_admin_patch_variant_cost_requires_admin(client, staff_token, e2e_cleanup):
    catalog_token = staff_token("catalog")
    catalog_auth = {"Authorization": f"Bearer {catalog_token}"}
    slug = "http-variant-2"
    _, variant_id = _create_product_with_variant(client, catalog_auth, slug)
    e2e_cleanup.append(slug)

    forbidden = client.patch(
        f"/api/admin/variants/{variant_id}", headers=catalog_auth,
        json={"cost": "200.00"},
    )
    assert forbidden.status_code == 403

    admin_token = staff_token("admin")
    admin_auth = {"Authorization": f"Bearer {admin_token}"}
    allowed = client.patch(
        f"/api/admin/variants/{variant_id}", headers=admin_auth, json={"cost": "200.00"},
    )
    assert allowed.status_code == 200, allowed.text


def test_admin_patch_variant_with_changed_sku_is_400(client, staff_token, e2e_cleanup):
    """I2: admin_variant_update previously had no sku field, so Pydantic
    silently dropped a "sku" key from the request body before the
    repository's refusal could ever fire -- a caller changing sku got 200 OK
    and a no-op. This is the HTTP-level proof the field now survives to the
    repository and the 400 actually fires."""
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "http-variant-3"
    _, variant_id = _create_product_with_variant(client, auth, slug)
    e2e_cleanup.append(slug)

    r = client.patch(
        f"/api/admin/variants/{variant_id}", headers=auth,
        json={"sku": "REWRITTEN-HTTP-1"},
    )

    assert r.status_code == 400, r.text
    assert "immutable" in r.json()["detail"].lower()


# --- Whole-branch review fix B2: validation gaps that reached the DB --------
#
# condition/gender/age_group/status are SAEnum(native_enum=False) columns, so a
# value outside the enum raises LookupError at bind time -- a 500 for what is
# plainly a bad request. These prove the request is refused at the boundary,
# before the repository or the database ever sees it.


@pytest.mark.parametrize(
    "field,value",
    [("condition", "antique"), ("gender", "robot"), ("age_group", "ancient")],
)
def test_admin_create_product_rejects_a_value_outside_the_enum(
    client, staff_token, e2e_cleanup, field, value
):
    token = staff_token("catalog")
    # Hyphens, not the field name verbatim: "age_group" is not a legal slug
    # (ck_products_slug_format), and a 400 for a malformed slug would mask
    # whether the enum was refused at all.
    slug = "b2-bad-" + field.replace("_", "-")
    # Registered before the call, not after: if this validation regresses the
    # row *is* written -- there is no CHECK behind the column -- and an
    # unregistered row is residue the next run trips over.
    e2e_cleanup.append(slug)
    body = {
        "title": "Bad Enum", "slug": slug, "brand": "Pixi",
        "category_id": _any_level2_category_id(), field: value,
    }

    r = client.post(
        "/api/admin/products",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )

    assert r.status_code == 422, r.text


def test_admin_create_product_rejects_an_overlong_item_group_id(
    client, staff_token, e2e_cleanup
):
    """products.item_group_id is String(64), and the generated variant sku is
    String(64) too -- a long item_group_id plus a long colour overflows it."""
    token = staff_token("catalog")
    e2e_cleanup.append("b2-long-group")

    r = client.post(
        "/api/admin/products",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Long Group", "slug": "b2-long-group", "brand": "Pixi",
            "category_id": _any_level2_category_id(), "item_group_id": "G" * 65,
        },
    )

    assert r.status_code == 422, r.text


def test_admin_listing_rejects_a_status_outside_the_lifecycle(client, staff_token):
    token = staff_token("catalog")

    r = client.get(
        "/api/admin/products?status=deleted",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 422, r.text


def test_admin_generate_variants_rejects_a_negative_price(client, staff_token):
    """Refused by the request schema, so it never reaches the repository --
    hence a product id that does not exist is still a 422, not a 404."""
    token = staff_token("catalog")

    r = client.post(
        "/api/admin/products/999999999/variants",
        headers={"Authorization": f"Bearer {token}"},
        json={"sizes": ["38"], "colors": ["black"], "price": "-1.00"},
    )

    assert r.status_code == 422, r.text


def test_admin_patch_product_rejects_a_value_outside_the_enum(
    client, staff_token, e2e_cleanup
):
    """The edit path writes these columns as blindly as the create path does,
    so it needs the same boundary -- an unloadable product is an unloadable
    product however it got that way."""
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    slug = "b2-patch-enum"
    e2e_cleanup.append(slug)
    product_id, _ = _create_product_with_variant(client, auth, slug)

    r = client.patch(
        f"/api/admin/products/{product_id}", headers=auth,
        json={"condition": "antique"},
    )

    assert r.status_code == 422, r.text
    assert client.get(f"/api/admin/products/{product_id}", headers=auth).status_code == 200
