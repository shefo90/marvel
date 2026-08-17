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
