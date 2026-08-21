"""Product imagery: upload, ordering, the primary image, and per-locale alt text.

The database already enforces most of what matters here, and these tests are
mostly about surfacing that as something an operator can read:

* ``alt_text`` is NOT NULL with a not-blank CHECK — upload *requires* alt text,
  which is accessibility the schema insists on
* ``uq_product_images_primary_product`` / ``..._variant`` already guarantee at
  most one primary
* ``uq_product_images_position`` is NULLS NOT DISTINCT, so reordering cannot be
  done one row at a time — it collides with itself mid-update
"""

import io

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from models.categories import Category
from models.locales import Locale
from models.product_images import ProductImage
from models.product_image_translations import ProductImageTranslation
from models.users import User
from repositories.admin_catalog import create_product, generate_variants
from repositories.admin_images import (
    add_image,
    delete_image,
    reorder_images,
    set_primary_image,
    upsert_image_alt,
)


def _png(width=400, height=300, colour=(120, 40, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _level2_category(db) -> Category:
    """Reused if already in this session -- categories.list_id is UNIQUE, and
    more than one test needs a category twice inside one rolled-back session."""
    existing = db.query(Category).filter(Category.slug == "img-child").first()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="I1", slug="img-top",
        list_id="img_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="I2", slug="img-child",
        list_id="img_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _actor(db) -> User:
    existing = db.query(User).filter(User.email == "image-writer@example.com").first()
    if existing is not None:
        return existing
    user = User(
        email="image-writer@example.com", password_hash="x",
        full_name="Imager", role="catalog", is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _product(db, slug: str):
    cat, actor = _level2_category(db), _actor(db)
    return create_product(db, actor, {
        "title": "Sandal", "slug": slug, "brand": "Pixi", "category_id": cat.id,
    })


def _add(db, product, *, alt="A suede sandal", colour=(120, 40, 200), **kwargs):
    return add_image(
        db, _actor(db), product.id,
        data=_png(colour=colour), filename="photo.png", alt_text=alt, **kwargs,
    )


def test_an_upload_records_the_measured_dimensions(db, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-dims")

    image = _add(db, product)

    assert (image.width, image.height) == (400, 300)


def test_the_stored_url_points_at_the_file_that_was_written(db, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-url")

    image = _add(db, product)

    relative = image.url.removeprefix("/media/")
    assert (tmp_path / relative).exists()


def test_every_derivative_is_written(db, tmp_path, monkeypatch):
    """The storefront needs a thumbnail, a card and a full size. Generating them
    at upload rather than on request keeps the request path free of image work."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-derivatives")

    _add(db, product)

    written = {p.name.rsplit("-", 1)[1] for p in tmp_path.rglob("*.png")}
    assert written == {"thumb.png", "card.png", "full.png"}


def test_blank_alt_text_is_refused_before_the_database_sees_it(db, tmp_path, monkeypatch):
    """ck_product_images_alt_text_not_blank would otherwise be a 500. Alt text is
    required because an indexable image without it is inaccessible and invisible
    to image search."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-alt")

    with pytest.raises(HTTPException) as exc:
        _add(db, product, alt="   ")

    assert exc.value.status_code == 422


def test_a_file_that_is_not_an_image_is_refused_with_422(db, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-not-an-image")

    with pytest.raises(HTTPException) as exc:
        add_image(
            db, _actor(db), product.id,
            data=b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            filename="logo.svg", alt_text="A logo",
        )

    assert exc.value.status_code == 422


def test_the_first_image_becomes_the_primary(db, tmp_path, monkeypatch):
    """A product with images but no primary has nothing to show in a listing."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-first-primary")

    image = _add(db, product)

    assert image.is_primary is True


def test_later_images_are_not_primary_and_take_the_next_position(db, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-positions")

    first = _add(db, product, colour=(1, 2, 3))
    second = _add(db, product, colour=(4, 5, 6))

    assert second.is_primary is False
    assert [first.position, second.position] == [0, 1]


def test_promoting_an_image_demotes_the_previous_primary(db, tmp_path, monkeypatch):
    """uq_product_images_primary_product is a partial unique index: setting the
    new one without clearing the old is an IntegrityError, not a second primary."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-promote")
    first = _add(db, product, colour=(1, 2, 3))
    second = _add(db, product, colour=(4, 5, 6))

    set_primary_image(db, _actor(db), second.id)

    db.refresh(first)
    db.refresh(second)
    assert (first.is_primary, second.is_primary) == (False, True)


def test_reordering_swaps_positions_without_colliding(db, tmp_path, monkeypatch):
    """uq_product_images_position is NULLS NOT DISTINCT and not deferrable, so
    writing the new positions one row at a time hits the constraint halfway
    through -- the second row briefly holds a position the first still has."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-reorder")
    first = _add(db, product, colour=(1, 2, 3))
    second = _add(db, product, colour=(4, 5, 6))
    third = _add(db, product, colour=(7, 8, 9))

    reorder_images(db, _actor(db), product.id, [third.id, first.id, second.id])

    for image in (first, second, third):
        db.refresh(image)
    assert [third.position, first.position, second.position] == [0, 1, 2]


def test_reordering_refuses_a_list_that_is_not_the_whole_set(db, tmp_path, monkeypatch):
    """A partial list would leave the missing rows holding positions that now
    collide with the ones just written."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-reorder-partial")
    first = _add(db, product, colour=(1, 2, 3))
    _add(db, product, colour=(4, 5, 6))

    with pytest.raises(HTTPException) as exc:
        reorder_images(db, _actor(db), product.id, [first.id])

    assert exc.value.status_code == 400


def test_the_files_outlive_the_delete_until_it_commits(db, tmp_path, monkeypatch):
    """The unlink is queued, not performed, while the transaction is open.

    This test previously asserted the opposite -- that the files were gone the
    moment ``delete_image`` returned -- which is what made the pre-commit
    ordering look correct for as long as it did. It was pinning the bug.
    ``test_deleting_an_image_over_http`` covers the other half: once the request
    commits, the files really are removed.
    """
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-delete")
    image = _add(db, product)
    relative = image.url.removeprefix("/media/")
    assert (tmp_path / relative).exists()

    delete_image(db, _actor(db), image.id)

    assert (tmp_path / relative).exists(), "the transaction has not landed yet"


def test_deleting_one_of_two_rows_sharing_a_file_keeps_the_file(db, tmp_path, monkeypatch):
    """Keys are content hashes, so the same photograph on two products is one
    file. Deleting either row must not blank the other product's image."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    first_product = _product(db, "img-shared-a")
    second_product = create_product(db, _actor(db), {
        "title": "Other", "slug": "img-shared-b", "brand": "Pixi",
        "category_id": _level2_category(db).id,
    })
    one = _add(db, first_product)
    two = _add(db, second_product)
    assert one.url == two.url, "identical pixels must produce identical keys"

    delete_image(db, _actor(db), one.id)

    assert (tmp_path / two.url.removeprefix("/media/")).exists()


def test_deleting_the_primary_promotes_the_next_image(db, tmp_path, monkeypatch):
    """Otherwise a product keeps its images but loses the one a listing shows."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-delete-primary")
    first = _add(db, product, colour=(1, 2, 3))
    second = _add(db, product, colour=(4, 5, 6))

    delete_image(db, _actor(db), first.id)

    db.refresh(second)
    assert second.is_primary is True


def test_an_image_can_carry_arabic_alt_text(db, tmp_path, monkeypatch):
    """Section 8A: the Arabic page needs Arabic alt text, or it ships English to
    Arabic readers and to image search."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    if db.get(Locale, "ar") is None:
        db.add(Locale(
            code="ar", hreflang="ar", name_native="ar", text_direction="rtl",
            is_default=False, is_active=True, sort_order=2,
        ))
        db.flush()
    product = _product(db, "img-alt-locale")
    image = _add(db, product)

    upsert_image_alt(db, _actor(db), image.id, "ar", "صندل جلد")

    row = db.execute(
        select(ProductImageTranslation).where(
            ProductImageTranslation.product_image_id == image.id
        )
    ).scalar_one()
    assert row.locale == "ar"


def test_an_image_can_be_attached_to_one_variant(db, tmp_path, monkeypatch):
    """fk_product_images_variant is composite, so a variant of a *different*
    product is refused by the database. This is the happy path for it."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-variant")
    variant = generate_variants(
        db, _actor(db), product.id, ["38"], ["black"], {"price": "500.00"}
    )[0]

    image = _add(db, product, variant_id=variant.id)

    assert image.variant_id == variant.id


def test_a_variant_image_is_positioned_within_its_own_variant(db, tmp_path, monkeypatch):
    """uq_product_images_position is (product_id, variant_id, position), so a
    variant's first image is position 0 even when the product already has
    images at 0."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-variant-position")
    variant = generate_variants(
        db, _actor(db), product.id, ["38"], ["black"], {"price": "500.00"}
    )[0]
    product_level = _add(db, product, colour=(1, 2, 3))

    variant_level = _add(db, product, colour=(4, 5, 6), variant_id=variant.id)

    assert (product_level.position, variant_level.position) == (0, 0)


def test_uploading_to_a_missing_product_is_404(db, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)

    with pytest.raises(HTTPException) as exc:
        add_image(
            db, _actor(db), 999_999_999,
            data=_png(), filename="photo.png", alt_text="Alt",
        )

    assert exc.value.status_code == 404


def test_images_come_back_with_the_product(db, tmp_path, monkeypatch):
    """The editor loads a product in one call; images have to be part of it or
    the tab needs a second request that can disagree with the first."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    from repositories.admin_catalog import get_product_for_admin

    product = _product(db, "img-in-payload")
    _add(db, product)

    loaded = get_product_for_admin(db, product.id)

    assert len(loaded["images"]) == 1
    assert loaded["images"][0]["alt_text"] == "A suede sandal"


# --- Over HTTP: multipart upload, and the files actually being served --------

import uuid  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from repositories.register import create_staff_user  # noqa: E402

PASSWORD = "Adm1n-Img-Test!"


@pytest.fixture
def staff_token(client):
    created: list[int] = []

    def _make(role: str) -> str:
        email = f"admin-test-img-{role}-{uuid.uuid4().hex[:8]}@example.com"
        session = SessionLocal()
        try:
            user = create_staff_user(
                session, email=email, password=PASSWORD, full_name=f"Test {role}",
                role=role,
            )
            created.append(user.id)
        finally:
            session.close()
        r = client.post(
            "/api/en/auth/staff/login", json={"email": email, "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    yield _make

    session = SessionLocal()
    try:
        for uid in created:
            user = session.get(User, uid)
            if user is not None:
                session.delete(user)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def http_product(client):
    """A committed product to hang images on, removed afterwards."""
    from sqlalchemy import select as sa_select

    from models.products import Product

    slug = f"img-http-{uuid.uuid4().hex[:8]}"
    session = SessionLocal()
    try:
        category_id = session.execute(
            sa_select(Category.id).where(Category.level == 2).order_by(Category.id).limit(1)
        ).scalar_one()
        product = Product(
            item_group_id=f"IMGHTTP{uuid.uuid4().hex[:8].upper()}",
            slug=slug, title="HTTP Image Sandal", brand="Pixi",
            category_id=category_id, status="draft", tags=[], condition="new",
        )
        session.add(product)
        session.commit()
        product_id = product.id
    finally:
        session.close()

    yield product_id

    session = SessionLocal()
    try:
        for row in session.execute(
            sa_select(ProductImage).where(ProductImage.product_id == product_id)
        ).scalars():
            session.delete(row)
        product = session.get(Product, product_id)
        if product is not None:
            session.delete(product)
        session.commit()
    finally:
        session.close()


def test_uploading_an_image_requires_a_token(client, http_product):
    r = client.post(
        f"/api/admin/products/{http_product}/images",
        files={"file": ("photo.png", _png(), "image/png")},
        data={"alt_text": "A sandal"},
    )

    assert r.status_code == 403


def test_catalog_role_uploads_an_image(client, staff_token, http_product, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    token = staff_token("catalog")

    r = client.post(
        f"/api/admin/products/{http_product}/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", _png(640, 480), "image/png")},
        data={"alt_text": "A suede sandal"},
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["width"], body["height"]) == (640, 480)
    assert body["is_primary"] is True


def test_the_declared_content_type_is_not_believed(client, staff_token, http_product, tmp_path, monkeypatch):
    """The multipart part says image/png. It is a text file."""
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    token = staff_token("catalog")

    r = client.post(
        f"/api/admin/products/{http_product}/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", b"not an image", "image/png")},
        data={"alt_text": "A suede sandal"},
    )

    assert r.status_code == 422, r.text


def test_an_upload_without_alt_text_is_refused(client, staff_token, http_product, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    token = staff_token("catalog")

    r = client.post(
        f"/api/admin/products/{http_product}/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", _png(), "image/png")},
        data={"alt_text": "   "},
    )

    assert r.status_code == 422, r.text


def test_an_uploaded_image_is_served_back_at_its_url(client, staff_token, http_product):
    """The row is useless if the file is not reachable. This is the only test
    that proves the static mount and the stored URL agree, so it deliberately
    does NOT redirect the storage root: the mount binds MEDIA_ROOT at import,
    and a test that moved the files elsewhere would prove nothing about the
    path the application actually serves. The files it writes are removed at
    the end."""
    from pathlib import Path

    from core.config import MEDIA_ROOT

    token = staff_token("catalog")
    created = client.post(
        f"/api/admin/products/{http_product}/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.png", _png(), "image/png")},
        data={"alt_text": "A suede sandal"},
    )
    assert created.status_code == 201, created.text

    url = created.json()["url"]
    try:
        served = client.get(url)

        assert served.status_code == 200
        assert served.headers["content-type"] == "image/png"
        assert served.headers.get("x-content-type-options") == "nosniff"
    finally:
        key = url.removeprefix("/media/")
        stem, _, tail = key.rpartition("-")
        extension = tail.split(".")[-1]
        for size in ("thumb", "card", "full"):
            Path(MEDIA_ROOT, f"{stem}-{size}.{extension}").unlink(missing_ok=True)


def test_deleting_an_image_over_http(client, staff_token, http_product, tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    created = client.post(
        f"/api/admin/products/{http_product}/images",
        headers=auth,
        files={"file": ("photo.png", _png(), "image/png")},
        data={"alt_text": "A suede sandal"},
    )
    image_id = created.json()["id"]
    relative = created.json()["url"].removeprefix("/media/")
    assert (tmp_path / relative).exists()

    r = client.delete(f"/api/admin/images/{image_id}", headers=auth)

    assert r.status_code == 204, r.text
    loaded = client.get(f"/api/admin/products/{http_product}", headers=auth)
    assert loaded.json()["images"] == []
    # The request committed, so the queued unlink has run. This is the half of
    # the ordering contract that test_the_files_outlive_the_delete_until_it_commits
    # cannot see, and it exercises the real after_commit wiring rather than
    # calling run_pending by hand.
    assert not (tmp_path / relative).exists()


def test_a_rolled_back_delete_keeps_the_photograph(db, tmp_path, monkeypatch):
    """The row and its file must survive or vanish together.

    ``delete_image`` used to unlink the derivatives inside the transaction. If
    the commit then failed -- a deadlock, a constraint tripped later in the same
    request, a dropped connection -- the row came back and the photograph did
    not, leaving a product pointing at a URL with nothing behind it. Storage has
    no rollback, so the delete has to wait until the transaction is known to
    have landed.
    """
    monkeypatch.setattr("repositories.admin_images.storage.root", tmp_path)
    product = _product(db, "img-delete-rollback")
    image = _add(db, product)
    relative = image.url.removeprefix("/media/")

    delete_image(db, _actor(db), image.id)
    db.rollback()

    assert (tmp_path / relative).exists(), (
        "the transaction was rolled back, so the image row still exists — "
        "its file must too"
    )
