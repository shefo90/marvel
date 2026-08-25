"""The category picker behind the product create form.

``products.category_level`` is a generated column pinned to 2 with a composite
FK to ``categories(id, level)``, so a level-1 category is not a choice the
database will accept. Offering one in the picker would be offering an error.
"""

import uuid

import pytest

from core.db import SessionLocal
from models.categories import Category
from models.users import User
from repositories.admin_categories import list_categories_for_admin
from repositories.register import create_staff_user

PASSWORD = "Adm1n-Cat-Test!"


def _tree(db, stem: str) -> tuple[Category, Category]:
    """A level-1 parent and its level-2 child, in the rolled-back session."""
    top = Category(
        parent_id=None, level=1, name=f"Top {stem}", slug=f"cat-{stem}-top",
        list_id=f"cat_{stem}_top", position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name=f"Child {stem}", slug=f"cat-{stem}-child",
        list_id=f"cat_{stem}_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return top, child


def test_only_level_2_categories_are_offered(db):
    top, child = _tree(db, "level")

    ids = {row["id"] for row in list_categories_for_admin(db)}

    assert child.id in ids
    assert top.id not in ids


def test_each_row_carries_its_parent_name(db):
    """"Sandals" is meaningless on its own -- the operator needs "Shoes /
    Sandals", and two parents may each have a "Sandals"."""
    top, child = _tree(db, "parent")

    row = next(r for r in list_categories_for_admin(db) if r["id"] == child.id)

    assert row["parent_id"] == top.id
    assert row["parent_name"] == top.name


def test_an_inactive_category_is_returned_and_flagged(db):
    """Not hidden: a product may already sit in a category that was since
    deactivated, and a picker that omits it would silently show that product as
    having no category at all. The flag lets the UI mark it instead."""
    _, child = _tree(db, "inactive")
    child.is_active = False
    db.flush()

    row = next(r for r in list_categories_for_admin(db) if r["id"] == child.id)

    assert row["is_active"] is False


def test_rows_are_grouped_by_parent(db):
    """Ordered by parent then position, so the picker can render optgroups
    without sorting the list itself."""
    first, _ = _tree(db, "order-a")
    second_child = Category(
        parent_id=first.id, level=2, name="Second", slug="cat-order-a-second",
        list_id="cat_order_a_second", position=2, is_active=True, is_indexable=True,
    )
    db.add(second_child)
    db.flush()

    rows = [r for r in list_categories_for_admin(db) if r["parent_id"] == first.id]

    assert [r["position"] for r in rows] == sorted(r["position"] for r in rows)


# --- Over HTTP, with a real staff login -------------------------------------


def _login(client, email: str) -> str:
    r = client.post(
        "/api/en/auth/staff/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def staff_token(client):
    """A committed staff account, removed afterwards -- create_staff_user
    commits, so this cannot ride on the rolled-back session fixture."""
    created: list[int] = []

    def _make(role: str) -> str:
        email = f"admin-test-cat-{role}-{uuid.uuid4().hex[:8]}@example.com"
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


def test_the_category_list_requires_a_token(client):
    assert client.get("/api/admin/categories").status_code == 403


def test_support_role_cannot_read_the_category_list(client, staff_token):
    token = staff_token("support")

    r = client.get(
        "/api/admin/categories", headers={"Authorization": f"Bearer {token}"}
    )

    assert r.status_code == 403


def test_catalog_role_reads_the_category_list(client, staff_token):
    token = staff_token("catalog")

    r = client.get(
        "/api/admin/categories", headers={"Authorization": f"Bearer {token}"}
    )

    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert rows, "seed data provides level-2 categories"
    assert all(row["parent_id"] is not None for row in rows)
    assert {"id", "name", "slug", "parent_id", "parent_name", "position", "is_active"} <= set(rows[0])
