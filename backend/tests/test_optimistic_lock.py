"""Two operators editing one row, and the second one winning silently.

Open question 4 from the 2026-08-21 handoff. Nothing stopped two people opening
the same product, both editing, and the later save overwriting the earlier one
with no sign to either that it had happened -- the classic lost update. In a
shop with one operator it is theoretical. It stops being theoretical the day a
second person is hired, and by then the mechanism has to already be there,
because the symptom is silent.

The check is a comparison against ``updated_at``, which every one of these
tables already carries, so there is no migration and no new column. A caller
that sends ``expected_updated_at`` is saying "I edited the version that looked
like this"; if the row has moved on since, the write is refused with a 409 and
the operator is told to reload rather than being allowed to clobber.

**The field is optional, and that is a real compromise.** A caller that omits it
gets the old last-write-wins behaviour. Making it mandatory would be safer and
would also break every existing caller at once. The mitigation is that the admin
UI sends it from one place -- its service layer -- rather than from each screen,
so there is a single site to get right rather than one per form.

Note that ``updated_at`` is driven by ``onupdate=func.now()``, and ``now()`` in
Postgres is the *transaction* timestamp. Two updates inside one transaction
therefore produce the same ``updated_at``, so these tests supply a deliberately
stale value rather than trying to race two writes inside one test.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from repositories.admin_catalog import create_product, update_product, update_variant
from repositories.admin_taxonomy import (
    create_category,
    create_collection,
    update_category,
    update_collection,
)
from tests.test_admin_writes import _actor, _level2_category, _locale

STALE = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _tag() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture
def actor(db):
    _locale(db, "en")
    return _actor(db)


# --- categories ----------------------------------------------------------

def test_a_category_edit_against_a_stale_version_is_refused(db, actor):
    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    with pytest.raises(HTTPException) as exc:
        update_category(db, actor, category.id, {
            "name": "Renamed", "expected_updated_at": STALE,
        })

    assert exc.value.status_code == 409


def test_a_refused_category_edit_changes_nothing(db, actor):
    """A 409 that had already applied half the payload would be worse than no
    check at all -- the operator would be told the save failed and it partly
    had not."""
    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    with pytest.raises(HTTPException):
        update_category(db, actor, category.id, {
            "name": "Renamed", "expected_updated_at": STALE,
        })

    assert category.name == "Shoes"


def test_a_category_edit_against_the_current_version_is_allowed(db, actor):
    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    update_category(db, actor, category.id, {
        "name": "Renamed", "expected_updated_at": category.updated_at,
    })

    assert category.name == "Renamed"


def test_a_category_edit_that_sends_no_version_is_still_allowed(db, actor):
    """Backwards compatibility, stated as a test so that removing it is a
    deliberate act rather than an accident."""
    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    update_category(db, actor, category.id, {"name": "Renamed"})

    assert category.name == "Renamed"


# --- collections ---------------------------------------------------------

def test_a_collection_edit_against_a_stale_version_is_refused(db, actor):
    collection = create_collection(db, actor, {"name": "Edit", "slug": f"lock-{_tag()}"})

    with pytest.raises(HTTPException) as exc:
        update_collection(db, actor, collection.id, {
            "name": "Renamed", "expected_updated_at": STALE,
        })

    assert exc.value.status_code == 409


def test_a_collection_edit_against_the_current_version_is_allowed(db, actor):
    collection = create_collection(db, actor, {"name": "Edit", "slug": f"lock-{_tag()}"})

    update_collection(db, actor, collection.id, {
        "name": "Renamed", "expected_updated_at": collection.updated_at,
    })

    assert collection.name == "Renamed"


# --- products and variants -----------------------------------------------

def _product(db, actor):
    return create_product(db, actor, {
        "title": "Sandal", "slug": f"lock-{_tag()}", "brand": "Pixi",
        "category_id": _level2_category(db).id,
    })


def test_a_product_edit_against_a_stale_version_is_refused(db, actor):
    product = _product(db, actor)

    with pytest.raises(HTTPException) as exc:
        update_product(db, actor, product.id, {
            "brand": "Other", "expected_updated_at": STALE,
        })

    assert exc.value.status_code == 409


def test_a_product_edit_against_the_current_version_is_allowed(db, actor):
    product = _product(db, actor)

    update_product(db, actor, product.id, {
        "brand": "Other", "expected_updated_at": product.updated_at,
    })

    assert product.brand == "Other"


def test_a_variant_edit_against_a_stale_version_is_refused(db, actor):
    from repositories.admin_catalog import generate_variants

    product = _product(db, actor)
    variant = generate_variants(
        db, actor, product.id, ["38"], ["black"], {"price": "100.00"},
    )[0]

    with pytest.raises(HTTPException) as exc:
        update_variant(db, actor, variant.id, {
            "stock_quantity": 5, "expected_updated_at": STALE,
        })

    assert exc.value.status_code == 409


def test_the_conflict_tells_the_operator_what_to_do(db, actor):
    """A 409 whose body says "conflict" leaves the operator guessing. The one
    action that resolves this is reloading, so the message says so."""
    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    with pytest.raises(HTTPException) as exc:
        update_category(db, actor, category.id, {
            "name": "Renamed", "expected_updated_at": STALE,
        })

    assert "reload" in exc.value.detail.lower()


# --- the version has to reach the client ---------------------------------
#
# A guard the caller cannot satisfy is worse than no guard: the screen would
# have to either omit the field (and lose the protection) or invent a value
# (and be refused every time). Each read that backs an edit form therefore has
# to report the version the form was built from.

def test_the_admin_tree_reports_each_categorys_version(db, actor):
    from repositories.admin_taxonomy import list_category_tree_for_admin

    category = create_category(db, actor, {"name": "Shoes", "slug": f"lock-{_tag()}"})

    tree = list_category_tree_for_admin(db)
    node = next(n for n in tree if n["id"] == category.id)

    assert node["updated_at"] == category.updated_at


def test_the_admin_collection_list_reports_each_version(db, actor):
    from repositories.admin_taxonomy import list_collections_for_admin

    collection = create_collection(db, actor, {"name": "Edit", "slug": f"lock-{_tag()}"})

    rows = list_collections_for_admin(db)
    row = next(r for r in rows if r["id"] == collection.id)

    assert row["updated_at"] == collection.updated_at


def test_the_admin_product_detail_reports_the_version_of_each_variant(db, actor):
    """The variant grid edits rows in place, so each row needs its own version
    -- the product's would refuse an edit to variant B because variant A moved."""
    from repositories.admin_catalog import generate_variants, get_product_for_admin

    product = _product(db, actor)
    variant = generate_variants(
        db, actor, product.id, ["38"], ["black"], {"price": "100.00"},
    )[0]

    detail = get_product_for_admin(db, product.id)

    assert detail["updated_at"] == product.updated_at
    row = next(v for v in detail["variants"] if v["id"] == variant.id)
    assert row["updated_at"] == variant.updated_at


# --- over HTTP -----------------------------------------------------------
#
# The repository tests above prove the guard. This proves it is reachable: the
# field has to survive Pydantic on the way in, and the version has to survive
# the response model on the way out. A response_model that omits updated_at
# would strip it silently and leave the screen with nothing to send back.

from tests.test_admin_catalog import e2e_cleanup, staff_token  # noqa: E402,F401


@pytest.fixture
def http_category(client, staff_token):  # noqa: F811
    """Create categories over HTTP and remove them afterwards.

    These requests commit -- that is the point of testing over HTTP -- so
    without this the development database gains two categories per run, which
    is the accumulation just fixed for orders reappearing under a new name.
    The taxonomy API has no delete (see the module docstring in
    routes/admin_taxonomy.py), so cleanup goes direct to the table.
    """
    created: list[int] = []

    def _make(auth: dict, **overrides) -> dict:
        body = {"name": "Lockable", "slug": f"http-lock-{_tag()}"}
        body.update(overrides)
        response = client.post(
            "/api/admin/taxonomy/categories", headers=auth, json=body
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["id"])
        return response.json()

    yield _make

    from core.db import SessionLocal
    from models.categories import Category

    session = SessionLocal()
    try:
        for category_id in created:
            row = session.get(Category, category_id)
            if row is not None:
                session.delete(row)
        session.commit()
    finally:
        session.close()


def test_a_stale_patch_over_http_is_a_409(client, staff_token, http_category):  # noqa: F811
    auth = {"Authorization": f"Bearer {staff_token('catalog')}"}
    category_id = http_category(auth)["id"]

    r = client.patch(
        f"/api/admin/taxonomy/categories/{category_id}",
        headers=auth,
        json={"name": "Renamed", "expected_updated_at": "2020-01-01T00:00:00+00:00"},
    )

    assert r.status_code == 409, r.text
    assert "reload" in r.json()["detail"].lower()


def test_the_category_tree_over_http_carries_the_version(client, staff_token, http_category):  # noqa: F811
    auth = {"Authorization": f"Bearer {staff_token('catalog')}"}
    category_id = http_category(auth, name="Versioned")["id"]

    tree = client.get("/api/admin/taxonomy/categories", headers=auth).json()
    node = next(n for n in tree if n["id"] == category_id)

    assert node["updated_at"], "the edit form has nothing to send back without this"

    # And the value it reports is one the guard accepts.
    ok = client.patch(
        f"/api/admin/taxonomy/categories/{category_id}", headers=auth,
        json={"name": "Renamed", "expected_updated_at": node["updated_at"]},
    )
    assert ok.status_code == 200, ok.text
