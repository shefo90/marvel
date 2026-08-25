"""Creating and editing offers from the back-office.

The database ties each promotion's value columns to its ``type`` with CHECK
constraints, so most of what these assert is that the operator gets a sentence
instead of an IntegrityError. That matters more here than elsewhere: these rows
price real baskets, so a half-specified promotion is not a validation nicety —
it is a wrong number on somebody's order.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models.categories import Category
from models.products import Product
from models.users import User
from repositories.admin_promotions import (
    create_promotion,
    get_promotion,
    list_promotions,
    set_targets,
    update_promotion,
)


def _actor(db) -> User:
    existing = db.query(User).filter(User.email == "promo-writer@example.com").first()
    if existing is not None:
        return existing
    user = User(
        email="promo-writer@example.com", password_hash="x", full_name="Promoter",
        role="catalog", is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _category(db) -> Category:
    existing = db.query(Category).filter(Category.slug == "promo-child").first()
    if existing is not None:
        return existing
    top = Category(
        parent_id=None, level=1, name="PR1", slug="promo-top", list_id="promo_top",
        position=1, is_active=True, is_indexable=True,
    )
    db.add(top)
    db.flush()
    child = Category(
        parent_id=top.id, level=2, name="PR2", slug="promo-child",
        list_id="promo_child", position=1, is_active=True, is_indexable=True,
    )
    db.add(child)
    db.flush()
    return child


def _product(db, slug: str) -> Product:
    product = Product(
        item_group_id=f"PROMO-{slug.upper()}", slug=slug, title=slug, brand="Pixi",
        category_id=_category(db).id, status="draft", tags=[], condition="new",
    )
    db.add(product)
    db.flush()
    return product


def _percentage_payload(**overrides) -> dict:
    payload = {
        "name": "Eid 20% off",
        "type": "percentage",
        "discount_percent": Decimal("20.00"),
        "targets": [{"target_type": "all", "target_id": None}],
    }
    payload.update(overrides)
    return payload


def test_a_percentage_promotion_is_created_with_its_targets(db):
    promotion = create_promotion(db, _actor(db), _percentage_payload())

    assert promotion.type == "percentage"
    assert len(promotion.targets) == 1
    assert promotion.created_by_user_id == _actor(db).id


def test_a_promotion_must_carry_at_least_one_target(db):
    """A promotion with no targets applies to nothing, so saving one is almost
    certainly a mistake -- and a silent one, since nothing errors at price time."""
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(targets=[]))

    assert exc.value.status_code == 422


def test_a_percentage_promotion_needs_a_percentage(db):
    with pytest.raises(HTTPException) as exc:
        create_promotion(
            db, _actor(db), _percentage_payload(discount_percent=None)
        )

    assert exc.value.status_code == 422


@pytest.mark.parametrize("percent", ["0", "-5", "150"])
def test_a_percentage_outside_one_to_a_hundred_is_refused(db, percent):
    with pytest.raises(HTTPException) as exc:
        create_promotion(
            db, _actor(db), _percentage_payload(discount_percent=Decimal(percent))
        )

    assert exc.value.status_code == 422


def test_a_percentage_promotion_cannot_also_carry_a_fixed_amount(db):
    """ck_promotions_percentage_shape refuses it; this refuses it readably."""
    with pytest.raises(HTTPException) as exc:
        create_promotion(
            db, _actor(db),
            _percentage_payload(discount_amount=Decimal("50.00")),
        )

    assert exc.value.status_code == 422


def test_a_fixed_promotion_needs_an_amount(db):
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            type="fixed", discount_percent=None, discount_amount=None,
        ))

    assert exc.value.status_code == 422


def test_a_bogo_promotion_needs_its_quantities(db):
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            type="bogo", discount_percent=None, buy_quantity=1,
        ))

    assert exc.value.status_code == 422


def test_a_complete_bogo_promotion_is_accepted(db):
    promotion = create_promotion(db, _actor(db), _percentage_payload(
        name="Buy 2 get 1 free", type="bogo", discount_percent=None,
        buy_quantity=2, get_quantity=1, get_discount_percent=Decimal("100.00"),
    ))

    assert promotion.buy_quantity == 2


def test_a_window_that_ends_before_it_starts_is_refused(db):
    """It would never be live -- a silent no-op rather than an error the
    operator would notice."""
    now = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            starts_at=now, ends_at=now - timedelta(days=1),
        ))

    assert exc.value.status_code == 422


def test_a_target_needs_an_id_unless_it_is_everything(db):
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            targets=[{"target_type": "product", "target_id": None}]
        ))

    assert exc.value.status_code == 422


def test_target_all_must_not_carry_an_id(db):
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            targets=[{"target_type": "all", "target_id": 7}]
        ))

    assert exc.value.status_code == 422


def test_a_target_pointing_at_nothing_is_refused(db):
    """A target whose row does not exist matches nothing, so the promotion
    silently does nothing -- the worst kind of wrong."""
    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(
            targets=[{"target_type": "product", "target_id": 999_999_999}]
        ))

    assert exc.value.status_code == 422


def test_a_product_target_is_accepted_when_the_product_exists(db):
    product = _product(db, "promo-target-real")

    promotion = create_promotion(db, _actor(db), _percentage_payload(
        targets=[{"target_type": "product", "target_id": product.id}]
    ))

    assert promotion.targets[0].target_id == product.id


def test_the_switch_can_be_turned_off_without_touching_the_dates(db):
    """is_active and the window are independent: pausing an offer must not
    require rewriting when it runs."""
    promotion = create_promotion(db, _actor(db), _percentage_payload())

    updated = update_promotion(db, _actor(db), promotion.id, {"is_active": False})

    assert updated.is_active is False
    assert updated.starts_at is None


def test_editing_keeps_the_shape_valid(db):
    promotion = create_promotion(db, _actor(db), _percentage_payload())

    with pytest.raises(HTTPException) as exc:
        update_promotion(db, _actor(db), promotion.id, {"discount_percent": Decimal("0")})

    assert exc.value.status_code == 422


def test_targets_are_replaced_as_a_set(db):
    """Replaced rather than appended: the operator sees one list and edits it,
    so a save has to mean "this is now the list"."""
    product = _product(db, "promo-retarget")
    promotion = create_promotion(db, _actor(db), _percentage_payload())

    set_targets(db, _actor(db), promotion.id, [
        {"target_type": "product", "target_id": product.id}
    ])

    refreshed = get_promotion(db, promotion.id)
    assert [t.target_type for t in refreshed.targets] == ["product"]


def test_the_same_target_cannot_be_added_twice(db):
    product = _product(db, "promo-dupe")

    with pytest.raises(HTTPException) as exc:
        create_promotion(db, _actor(db), _percentage_payload(targets=[
            {"target_type": "product", "target_id": product.id},
            {"target_type": "product", "target_id": product.id},
        ]))

    assert exc.value.status_code == 422


def test_the_listing_returns_promotions_with_their_targets(db):
    create_promotion(db, _actor(db), _percentage_payload(name="Listed offer"))

    rows = list_promotions(db)

    listed = next(row for row in rows if row["name"] == "Listed offer")
    assert listed["targets"][0]["target_type"] == "all"


def test_loading_a_promotion_that_is_not_there_is_404(db):
    with pytest.raises(HTTPException) as exc:
        get_promotion(db, 999_999_999)

    assert exc.value.status_code == 404


# --- Over HTTP --------------------------------------------------------------

import uuid  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from models.promotions import Promotion  # noqa: E402
from repositories.register import create_staff_user  # noqa: E402

PASSWORD = "Adm1n-Promo-Test!"


@pytest.fixture
def staff_token(client):
    created: list[int] = []

    def _make(role: str) -> str:
        email = f"admin-test-promo-{role}-{uuid.uuid4().hex[:8]}@example.com"
        session = SessionLocal()
        try:
            user = create_staff_user(
                session, email=email, password=PASSWORD,
                full_name=f"Test {role}", role=role,
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
def created_promotions():
    """Removes whatever a test committed, so the suite stays repeatable."""
    ids: list[int] = []
    yield ids

    session = SessionLocal()
    try:
        for promotion_id in ids:
            promotion = session.get(Promotion, promotion_id)
            if promotion is not None:
                session.delete(promotion)
        session.commit()
    finally:
        session.close()


def test_the_promotion_list_requires_a_token(client):
    assert client.get("/api/admin/promotions").status_code == 403


def test_support_role_cannot_read_promotions(client, staff_token):
    token = staff_token("support")

    r = client.get(
        "/api/admin/promotions", headers={"Authorization": f"Bearer {token}"}
    )

    assert r.status_code == 403


def test_catalog_role_creates_a_promotion_over_http(client, staff_token, created_promotions):
    token = staff_token("catalog")

    r = client.post(
        "/api/admin/promotions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "HTTP 15% off",
            "type": "percentage",
            "discount_percent": "15.00",
            "targets": [{"target_type": "all", "target_id": None}],
        },
    )

    assert r.status_code == 201, r.text
    created_promotions.append(r.json()["id"])
    assert r.json()["targets"][0]["target_type"] == "all"


def test_a_promotion_without_targets_is_refused_at_the_boundary(client, staff_token):
    token = staff_token("catalog")

    r = client.post(
        "/api/admin/promotions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Applies to nothing",
            "type": "percentage",
            "discount_percent": "15.00",
            "targets": [],
        },
    )

    assert r.status_code == 422, r.text


def test_a_promotion_can_be_paused_over_http(client, staff_token, created_promotions):
    token = staff_token("catalog")
    auth = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/admin/promotions", headers=auth, json={
        "name": "Pausable", "type": "percentage", "discount_percent": "15.00",
        "targets": [{"target_type": "all", "target_id": None}],
    })
    promotion_id = created.json()["id"]
    created_promotions.append(promotion_id)

    r = client.patch(
        f"/api/admin/promotions/{promotion_id}", headers=auth, json={"is_active": False}
    )

    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_an_unknown_promotion_type_is_refused(client, staff_token):
    token = staff_token("catalog")

    r = client.post(
        "/api/admin/promotions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Nonsense", "type": "buy_the_shop",
            "targets": [{"target_type": "all", "target_id": None}],
        },
    )

    assert r.status_code == 422, r.text
