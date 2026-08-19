"""The cart sweeps, and what they must not destroy.

These drive ``_resolve`` directly rather than ``get_cart``. Every public entry
point in ``repositories.cart`` commits, and the sweeps are precisely the code
whose job is to act on carts left lying around -- proving them through a path
that commits would mean seeding the shared development database with abandoned
carts on every run. ``_resolve`` is the function the reactivation lives in, so
it is also the honest unit to test.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from core.enums import CartStatus
from models.cart_items import CartItem
from models.carts import Cart
from repositories.cart import _new_cart_token, _resolve
from tasks.carts import sweep_abandoned, sweep_expired


SIZES = ["38", "39", "40"]


def _real_variants(db, count: int):
    """cart_items has a composite FK on (variant_id, sku), so a basket cannot be
    faked with invented ids -- and uq_cart_items_cart_variant allows only one
    line per variant, so each line needs a variant of its own."""
    from repositories.admin_catalog import create_product, generate_variants
    from tests.test_admin_writes import _actor, _level2_category

    cat, actor = _level2_category(db), _actor(db)
    product = create_product(db, actor, {
        "title": "Sweep", "slug": "sweep-lifecycle", "brand": "Pixi",
        "category_id": cat.id,
    })
    return generate_variants(
        db, actor, product.id, SIZES[:count], ["black"], {"price": "100.00"}
    )


def _cart(db, *, idle_hours=0, expired=False, status=CartStatus.active, items=0) -> Cart:
    """A cart whose last activity was ``idle_hours`` ago.

    Times come from the database clock, the same one the sweeps compare against,
    so a slow test machine cannot drift the fixture past the cutoff.
    """
    now = db.execute(select(func.now())).scalar_one()
    cart = Cart(
        token=_new_cart_token(),
        status=status.value,
        locale="en",
        currency="EGP",
        item_count=items,
        subtotal=Decimal("0"),
        discount_total=Decimal("0"),
        total=Decimal("0"),
        last_activity_at=now - timedelta(hours=idle_hours),
        expires_at=now - timedelta(days=1) if expired else now + timedelta(days=30),
    )
    db.add(cart)
    db.flush()
    for variant in _real_variants(db, items):
        db.add(CartItem(
            cart_id=cart.id, variant_id=variant.id, sku=variant.sku,
            quantity=1, unit_price_snapshot=Decimal("100.00"),
        ))
    if items:
        db.flush()
    return cart


def _status(cart: Cart) -> str:
    return cart.status.value if hasattr(cart.status, "value") else cart.status


# --- the abandonment sweep ----------------------------------------------

def test_an_idle_cart_is_marked_abandoned(db):
    cart = _cart(db, idle_hours=48)

    sweep_abandoned(db, {})

    db.expire_all()
    refreshed = db.get(Cart, cart.id)
    assert _status(refreshed) == CartStatus.abandoned.value
    assert refreshed.abandoned_at is not None


def test_a_recently_active_cart_is_left_alone(db):
    cart = _cart(db, idle_hours=1)

    sweep_abandoned(db, {})

    db.expire_all()
    assert _status(db.get(Cart, cart.id)) == CartStatus.active.value


def test_the_abandonment_sweep_is_idempotent(db):
    """At-least-once delivery: a lease can expire mid-run and the job repeats."""
    cart = _cart(db, idle_hours=48)
    sweep_abandoned(db, {})
    db.expire_all()
    first_marked_at = db.get(Cart, cart.id).abandoned_at

    sweep_abandoned(db, {})

    db.expire_all()
    assert db.get(Cart, cart.id).abandoned_at == first_marked_at


# --- what abandonment must not cost the shopper -------------------------

def test_a_shopper_returning_to_an_abandoned_cart_gets_it_back(db):
    """The reason abandonment is a marker and not a demolition.

    Without this, the sweep would empty the basket of every shopper who took
    more than CART_ABANDONED_AFTER_HOURS to make up their mind.
    """
    cart = _cart(db, idle_hours=48, items=2)
    token = cart.token
    sweep_abandoned(db, {})
    db.expire_all()

    resolved = _resolve(db, locale="en", cart_token=token, claims=None, create=True)

    assert resolved.id == cart.id, "the shopper was issued a new cart"
    assert _status(resolved) == CartStatus.active.value
    assert resolved.abandoned_at is None
    assert db.execute(
        select(func.count()).select_from(CartItem).where(CartItem.cart_id == cart.id)
    ).scalar_one() == 2


# --- the expiry sweep ---------------------------------------------------

def test_a_cart_past_its_ttl_is_expired(db):
    cart = _cart(db, expired=True)

    sweep_expired(db, {})

    db.expire_all()
    assert _status(db.get(Cart, cart.id)) == CartStatus.expired.value


def test_an_abandoned_cart_still_expires_at_its_ttl(db):
    """Abandonment postpones nothing. expires_at is what ends a cart's life."""
    cart = _cart(db, idle_hours=48, expired=True, status=CartStatus.abandoned)

    sweep_expired(db, {})

    db.expire_all()
    assert _status(db.get(Cart, cart.id)) == CartStatus.expired.value


def test_an_expired_cart_is_not_recoverable(db):
    cart = _cart(db, expired=True)
    token = cart.token
    sweep_expired(db, {})
    db.expire_all()

    with pytest.raises(HTTPException) as exc:
        _resolve(db, locale="en", cart_token=token, claims=None, create=False)

    assert exc.value.status_code == 404


def test_a_cart_inside_its_ttl_is_left_alone(db):
    cart = _cart(db)

    sweep_expired(db, {})

    db.expire_all()
    assert _status(db.get(Cart, cart.id)) == CartStatus.active.value
