"""Server-side cart.

Owns every query, every rule and every commit for the cart domain. Routes never
touch SQLAlchemy.

**Never cached.** A cart is per-shopper mutable state; a shared cache is how one
shopper ends up seeing another's basket. ``services.cache`` is deliberately not
imported by this module.

Four design points worth stating, because each one exists to satisfy a specific
requirement rather than a preference:

1. **Rapid repeated clicks (section 15).** Every mutation takes
   ``SELECT ... FOR UPDATE`` on the cart row first, so concurrent requests for
   the same cart serialize instead of interleaving a read-then-write. The line
   write itself is ``INSERT ... ON CONFLICT (cart_id, variant_id) DO UPDATE``,
   so even without the lock two racing adds sum to one row instead of raising or
   producing two rows. Totals are recomputed by a SQL aggregate over
   ``cart_items``, never incremented in Python, so they cannot drift from the
   lines they claim to summarize.

2. **Idempotency.** ``cart_mutations`` has ``UNIQUE (cart_id, idempotency_key)``.
   A request carrying an ``Idempotency-Key`` that has already been applied is a
   *no-op that returns the same state* — checked after the cart lock is held, so
   under READ COMMITTED the replaying transaction is guaranteed to see the
   original committed row. The unique constraint is still the backstop.

3. **Price snapshots.** ``unit_price_snapshot`` is taken once, at add time, and
   totals are computed from it. A catalog price edit mid-session therefore shows
   up as ``price_changed`` on the line rather than silently repricing the basket.
   ``reprice_cart`` is the explicit path that adopts the new price and stamps
   ``last_repriced_at``.

4. **Attribution before an order exists (section 4).** ``cart_attributions``
   links the cart to an ``attribution_visitors`` row and to first/last
   ``attribution_touches``. First touch is written once and never overwritten
   (section 11A); last touch always advances. This is what lets the order
   snapshot be built at checkout from server-side state rather than from
   whatever the browser still happens to remember.

**Guest vs signed-in.** ``carts.token`` is the anonymous identity. A signed-in
shopper's cart is found by ``customer_id``. When a guest presents a cart token
*and* a shopper token, the guest cart is claimed; if that shopper already had a
cart, the two are merged by summing quantities on variant collision — spec open
question 6's documented rule.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status as http_status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.config import (
    CUSTOMER_CART_TTL_DAYS,
    DEFAULT_CURRENCY,
    GUEST_CART_TTL_DAYS,
)
from core.enums import ActorType, Availability, CartStatus
from models.attribution_touches import AttributionTouch
from models.attribution_visitors import AttributionVisitor
from models.cart_attributions import CartAttribution
from models.cart_items import CartItem
from models.cart_mutations import CartMutation
from models.carts import Cart
from models.customers import Customer
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from repositories.pricing import price_basket

ZERO = Decimal("0.00")

# GA4 event names, so ``logical_event_id`` is already the name of the event S3
# will emit and S5 will deduplicate against.
_EVENT_NAME = {
    "add": "add_to_cart",
    "remove": "remove_from_cart",
    "update_quantity": "update_cart",
    "apply_coupon": "select_promotion",
    "remove_coupon": "select_promotion",
    "reprice": "cart_reprice",
    "merge": "cart_merge",
    "clear": "remove_from_cart",
}

_COUPON_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")


# --- small helpers --------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_cart_token() -> str:
    """Opaque, unguessable, and short enough for ``carts.token`` (64 chars)."""
    return secrets.token_urlsafe(32)


def _logical_event_id(mutation_type: str, cart_id: int) -> str:
    """Stable id for the logical event this mutation represents.

    Generated here — at the actual state transition — because section 15 requires
    events to fire on the state transition rather than on a UI button click.
    S3/S5 reuse this string as the destination dedup key.
    """
    return f"{_EVENT_NAME.get(mutation_type, mutation_type)}_{cart_id}_{uuid4().hex}"


def _q(value) -> Decimal:
    return (Decimal(value or 0)).quantize(Decimal("0.01"))


def _enum_value(value) -> str | None:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _ttl_days(customer_id: int | None) -> int:
    # Open question 6's documented defaults: guest 30d sliding, customer 90d.
    return CUSTOMER_CART_TTL_DAYS if customer_id else GUEST_CART_TTL_DAYS


def _touch(cart: Cart) -> None:
    """Sliding expiry. Any interaction keeps the cart alive."""
    now = _now()
    cart.last_activity_at = now
    cart.expires_at = now + timedelta(days=_ttl_days(cart.customer_id))


# --- identity resolution --------------------------------------------------


def resolve_customer_id(db: Session, claims: dict | None) -> int | None:
    """Internal ``customers.id`` from an optional shopper access token.

    The token deliberately carries ``public_id`` (an opaque UUID) rather than
    the internal id — section 2 keeps ``customers.id`` off the browser — so this
    resolves the opaque handle back to the internal key on the server side.

    Guest-tolerant by design: ``None`` means "anonymous", which is a supported
    state, not an error. A token that decodes but points at no live customer *is*
    an error — treating it as a guest would silently orphan a signed-in
    shopper's cart.
    """
    if not claims:
        return None

    stmt = select(Customer.id).where(Customer.status == "active")
    public_id = claims.get("public_id")
    if public_id:
        try:
            stmt = stmt.where(Customer.public_id == UUID(str(public_id)))
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="invalid customer token",
            )
    elif claims.get("email"):
        stmt = stmt.where(Customer.email == claims["email"])
    else:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="invalid customer token",
        )

    customer_id = db.execute(stmt).scalar_one_or_none()
    if customer_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="invalid customer token",
        )
    return int(customer_id)


def _cart_by_token(db: Session, token: str, *, for_update: bool) -> Cart | None:
    stmt = select(Cart).where(Cart.token == token)
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _cart_by_customer(db: Session, customer_id: int, *, for_update: bool) -> Cart | None:
    stmt = (
        select(Cart)
        .where(
            Cart.customer_id == customer_id,
            # Abandoned too: the sweep flags a cart idle for a day, and a
            # signed-in shopper coming back must find the basket they left, not
            # an empty one. Ordering means a genuinely active cart still wins.
            Cart.status.in_([CartStatus.active.value, CartStatus.abandoned.value]),
        )
        .order_by(Cart.last_activity_at.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _reactivate_if_abandoned(cart: Cart | None) -> None:
    """Undo the abandonment sweep for a shopper who came back.

    ``abandoned`` is an analytics marker, not a demolition. ``tasks.carts``
    flags any cart idle past CART_ABANDONED_AFTER_HOURS so abandonment can be
    counted and, later, recovered by email -- but the basket itself has to
    survive, or every shopper who takes a day to decide loses it. ``expires_at``,
    refreshed on every touch, is what actually ends a cart's life.
    """
    if cart is not None and _enum_value(cart.status) == CartStatus.abandoned.value:
        cart.status = CartStatus.active.value
        cart.abandoned_at = None


def _create_cart(db: Session, *, locale: str, customer_id: int | None) -> Cart:
    now = _now()
    cart = Cart(
        token=_new_cart_token(),
        customer_id=customer_id,
        status=CartStatus.active.value,
        locale=locale,
        currency=DEFAULT_CURRENCY,
        item_count=0,
        subtotal=ZERO,
        discount_total=ZERO,
        total=ZERO,
        last_activity_at=now,
        expires_at=now + timedelta(days=_ttl_days(customer_id)),
    )
    db.add(cart)
    db.flush()
    return cart


def _resolve(
    db: Session,
    *,
    locale: str,
    cart_token: str | None,
    claims: dict | None,
    create: bool,
) -> Cart:
    """Find the caller's cart, optionally creating one.

    Ownership rule: an active cart bound to a customer may only be reached by
    that customer's token. Presenting only the opaque cart token is enough for a
    guest cart — that token *is* the identity — but it does not grant access to
    a cart that has since been claimed by a signed-in shopper.
    """
    customer_id = resolve_customer_id(db, claims)

    cart = None
    if cart_token:
        cart = _cart_by_token(db, cart_token, for_update=True)
        _reactivate_if_abandoned(cart)
        if cart is not None and _enum_value(cart.status) != CartStatus.active.value:
            # Converted and expired carts are not reusable. A new one is issued
            # rather than silently resurrecting an ordered basket.
            cart = None
        if (
            cart is not None
            and cart.customer_id is not None
            and cart.customer_id != customer_id
        ):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN, detail="cart not yours"
            )

    if customer_id is not None:
        owned = _cart_by_customer(db, customer_id, for_update=True)
        _reactivate_if_abandoned(owned)
        if cart is None:
            cart = owned
        elif owned is not None and owned.id != cart.id:
            # Guest cart presented by a shopper who already has one: merge the
            # guest lines in, summing quantities on collision (open question 6).
            _merge_carts(db, source=cart, target=owned)
            cart = owned
        elif cart.customer_id is None:
            cart.customer_id = customer_id

    if cart is None:
        if not create:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="cart not found"
            )
        cart = _create_cart(db, locale=locale, customer_id=customer_id)

    if locale and cart.locale != locale:
        # The locale is a path segment, so the cart follows the URL the shopper
        # is actually on. Nothing money-bearing depends on it.
        cart.locale = locale
    return cart


# --- idempotency + mutation log ------------------------------------------


def _replayed(db: Session, cart_id: int, idempotency_key: str | None) -> CartMutation | None:
    """The already-applied mutation for this key, if any.

    Called while holding the cart lock, so a concurrent duplicate is either
    still blocked (and will see the committed row when it proceeds) or already
    finished.
    """
    if not idempotency_key:
        return None
    return db.execute(
        select(CartMutation).where(
            CartMutation.cart_id == cart_id,
            CartMutation.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def _record_mutation(
    db: Session,
    *,
    cart: Cart,
    mutation_type: str,
    idempotency_key: str | None = None,
    variant_id: int | None = None,
    quantity_delta: int | None = None,
    quantity_after: int | None = None,
    unit_price: Decimal | None = None,
    value_delta: Decimal | None = None,
) -> str:
    """Append one row per change. Never updated, never deleted."""
    logical_event_id = _logical_event_id(mutation_type, cart.id)
    stmt = (
        pg_insert(CartMutation.__table__)
        .values(
            cart_id=cart.id,
            idempotency_key=idempotency_key,
            mutation_type=mutation_type,
            variant_id=variant_id,
            quantity_delta=quantity_delta,
            quantity_after=quantity_after,
            unit_price_at_mutation=unit_price,
            value_delta=value_delta,
            logical_event_id=logical_event_id,
            occurred_at=func.now(),
            actor_type=ActorType.customer.value,
            created_at=func.now(),
        )
        # Backstop for a true race that got past the cart lock: the unique
        # constraint wins and the duplicate write is simply dropped.
        .on_conflict_do_nothing(constraint="uq_cart_mutations_idempotency")
    )
    db.execute(stmt)
    return logical_event_id


# --- catalog lookups ------------------------------------------------------


def _load_variant(db: Session, *, variant_id: int | None, sku: str | None) -> ProductVariant:
    if variant_id is None and not sku:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="variant_id or sku is required",
        )
    stmt = (
        select(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(ProductVariant.is_active.is_(True), Product.status == "active")
    )
    stmt = stmt.where(
        ProductVariant.id == variant_id if variant_id is not None else ProductVariant.sku == sku
    )
    variant = db.execute(stmt).scalar_one_or_none()
    if variant is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="variant not found"
        )
    return variant


def _assert_purchasable(variant: ProductVariant, quantity: int) -> None:
    if _enum_value(variant.availability) == Availability.out_of_stock.value:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="variant out of stock"
        )
    if quantity > variant.stock_quantity:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"only {variant.stock_quantity} left for {variant.sku}",
        )


# --- totals ---------------------------------------------------------------


class _SnapshotVariant:
    """A cart line, shaped like a variant for ``price_basket``.

    The cart prices from its own snapshots, not from the live catalog: a price
    edit mid-session must surface as ``price_changed`` on the line rather than
    silently repricing the basket. Promotions are still evaluated live, because
    they are time-windowed by nature, and checkout refuses to convert a cart
    whose snapshot has drifted from the catalog — so whenever an order can be
    placed at all, both sides are pricing the same numbers.
    """

    __slots__ = ("id", "product_id", "price", "sale_price")

    def __init__(self, item: CartItem, product_id: int):
        self.id = item.variant_id
        self.product_id = product_id
        self.price = item.unit_price_snapshot
        self.sale_price = item.unit_sale_price_snapshot


def _recalculate(db: Session, cart: Cart) -> None:
    """Recompute the cart header from its lines, through the shared pricing.

    Deliberately a full recomputation rather than an increment: an incremented
    total can disagree with the lines it summarizes, and section 15 tests
    exactly that after rapid repeated clicks.

    ``subtotal`` is the list-price sum and ``discount_total`` the whole saving —
    markdown plus promotion — so ``total = subtotal - discount_total`` mirrors
    the ``orders`` totals identity (``total = subtotal - discount + tax +
    shipping``, with tax 0 because prices are VAT-inclusive).

    ``repositories/pricing.py`` is called here and at checkout, and nowhere
    else. Two implementations of one rule is the defect that put one shopper in
    two ``customers`` rows; a second copy of *this* rule shows one price and
    charges another.
    """
    db.flush()
    items = list(
        db.execute(select(CartItem).where(CartItem.cart_id == cart.id)).scalars()
    )

    product_ids = dict(
        db.execute(
            select(ProductVariant.id, ProductVariant.product_id).where(
                ProductVariant.id.in_([item.variant_id for item in items])
            )
        ).all()
    ) if items else {}

    priced = price_basket(
        db,
        [
            (_SnapshotVariant(item, product_ids.get(item.variant_id, 0)), item.quantity)
            for item in items
        ],
    )
    by_variant = {line.variant_id: line for line in priced}

    subtotal = Decimal("0.00")
    discount = Decimal("0.00")
    count = 0
    for item in items:
        line = by_variant.get(item.variant_id)
        count += item.quantity
        if line is None:
            continue
        item.promotion_id = line.promotion_id
        item.discount_amount = line.discount_amount
        item.discount_source = line.discount_source
        subtotal += line.unit_list_price * item.quantity
        # The markdown and the promotion are both savings to the shopper; only
        # the promotion half is campaign cost, which is what discount_source
        # records on the line.
        markdown = (line.unit_list_price - line.unit_price) * item.quantity
        discount += markdown + line.discount_amount

    cart.item_count = int(count)
    cart.subtotal = _q(subtotal)
    cart.discount_total = _q(discount)
    cart.total = _q(subtotal) - _q(discount)
    _touch(cart)
    db.flush()


# --- serialization --------------------------------------------------------


def _serialize_attribution(db: Session, cart_id: int) -> dict | None:
    row = db.execute(
        select(CartAttribution).where(CartAttribution.cart_id == cart_id)
    ).scalar_one_or_none()
    if row is None:
        return None

    visitor_token = None
    if row.visitor_id:
        visitor_token = db.execute(
            select(AttributionVisitor.visitor_token).where(
                AttributionVisitor.id == row.visitor_id
            )
        ).scalar_one_or_none()

    def touch(touch_id):
        if not touch_id:
            return None
        return db.execute(
            select(AttributionTouch).where(AttributionTouch.id == touch_id)
        ).scalar_one_or_none()

    first, last = touch(row.first_touch_id), touch(row.last_touch_id)
    return {
        "visitor_token": visitor_token,
        "first_touch_id": row.first_touch_id,
        "last_touch_id": row.last_touch_id,
        "first_touch_source": first.source if first else None,
        "first_touch_medium": first.medium if first else None,
        "first_touch_campaign": first.campaign if first else None,
        "last_touch_source": last.source if last else None,
        "last_touch_medium": last.medium if last else None,
        "last_touch_campaign": last.campaign if last else None,
    }


def _serialize(
    db: Session,
    cart: Cart,
    *,
    replayed: bool = False,
    logical_event_id: str | None = None,
) -> dict:
    # Core-level writes (the ON CONFLICT upserts) bypass the identity map, so
    # cached ORM state has to be dropped before reading the lines back. Flush
    # first: ``expire_all`` *discards* pending in-memory changes, so expiring
    # before flushing would silently throw away edits made in this call.
    db.flush()
    db.expire_all()
    rows = db.execute(
        select(CartItem, ProductVariant, Product, ProductTranslation.title)
        .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(
            ProductTranslation,
            (ProductTranslation.product_id == Product.id)
            & (ProductTranslation.locale == cart.locale),
        )
        .where(CartItem.cart_id == cart.id)
        .order_by(CartItem.id)
    ).all()

    items = []
    for item, variant, product, translated_title in rows:
        list_price = _q(item.unit_price_snapshot)
        effective = _q(
            item.unit_sale_price_snapshot
            if item.unit_sale_price_snapshot is not None
            else item.unit_price_snapshot
        )
        current_effective = _q(
            variant.sale_price if variant.sale_price is not None else variant.price
        )
        items.append(
            {
                "variant_id": item.variant_id,
                "sku": item.sku,
                "product_id": product.id,
                "title": translated_title or product.title,
                "quantity": item.quantity,
                "unit_price_snapshot": list_price,
                "unit_sale_price_snapshot": (
                    _q(item.unit_sale_price_snapshot)
                    if item.unit_sale_price_snapshot is not None
                    else None
                ),
                "unit_price_effective": effective,
                # The promotion is on the line too, not only in the header --
                # otherwise the lines a shopper reads do not add up to the total
                # they are asked to pay.
                "line_total": effective * item.quantity - _q(item.discount_amount),
                "line_discount": (
                    (list_price - effective) * item.quantity + _q(item.discount_amount)
                ),
                "promotion_id": item.promotion_id,
                "discount_source": _enum_value(item.discount_source),
                "price_snapshot_at": item.price_snapshot_at,
                "last_repriced_at": item.last_repriced_at,
                "price_changed": current_effective != effective,
                "current_unit_price": current_effective,
                "added_from_list_id": item.added_from_list_id,
                "added_from_list_name": item.added_from_list_name,
                "added_from_index": item.added_from_index,
                "item_coupon_code": item.item_coupon_code,
                "availability": _enum_value(variant.availability),
                "stock_quantity": variant.stock_quantity,
            }
        )

    return {
        "token": cart.token,
        "status": _enum_value(cart.status),
        "locale": cart.locale,
        "currency": cart.currency,
        "item_count": cart.item_count,
        "subtotal": _q(cart.subtotal),
        "discount_total": _q(cart.discount_total),
        "total": _q(cart.total),
        "coupon_code": cart.coupon_code,
        "items": items,
        "attribution": _serialize_attribution(db, cart.id),
        "replayed": replayed,
        "logical_event_id": logical_event_id,
        "last_activity_at": cart.last_activity_at,
        "expires_at": cart.expires_at,
        "updated_at": cart.updated_at,
    }


# --- line writes ----------------------------------------------------------


def _upsert_line(
    db: Session,
    *,
    cart_id: int,
    variant: ProductVariant,
    quantity_delta: int,
    added_from_list_id: str | None = None,
    added_from_list_name: str | None = None,
    added_from_index: int | None = None,
    item_coupon_code: str | None = None,
) -> int:
    """Add ``quantity_delta`` to a line, creating it if absent. Returns the new
    quantity.

    ``INSERT ... ON CONFLICT DO UPDATE`` rather than read-then-write: the unique
    constraint on ``(cart_id, variant_id)`` turns two racing adds into one row
    with the summed quantity instead of an integrity error or a lost update.

    On conflict the **price snapshot is not restamped** — the price the shopper
    saw when the line was first created is the price that stands until an
    explicit reprice. The list attribution is likewise kept from the first add:
    that is the surface that genuinely caused the item to enter the cart.
    """
    table = CartItem.__table__
    stmt = pg_insert(table).values(
        cart_id=cart_id,
        variant_id=variant.id,
        sku=variant.sku,
        quantity=quantity_delta,
        unit_price_snapshot=variant.price,
        unit_sale_price_snapshot=variant.sale_price,
        price_snapshot_at=func.now(),
        added_from_list_id=added_from_list_id,
        added_from_list_name=added_from_list_name,
        added_from_index=added_from_index,
        item_coupon_code=item_coupon_code,
        created_at=func.now(),
        updated_at=func.now(),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cart_items_cart_variant",
        set_={
            "quantity": table.c.quantity + stmt.excluded.quantity,
            "added_from_list_id": func.coalesce(
                table.c.added_from_list_id, stmt.excluded.added_from_list_id
            ),
            "added_from_list_name": func.coalesce(
                table.c.added_from_list_name, stmt.excluded.added_from_list_name
            ),
            "added_from_index": func.coalesce(
                table.c.added_from_index, stmt.excluded.added_from_index
            ),
            "item_coupon_code": func.coalesce(
                stmt.excluded.item_coupon_code, table.c.item_coupon_code
            ),
            "updated_at": func.now(),
        },
    ).returning(table.c.quantity)
    return int(db.execute(stmt).scalar_one())


def _merge_carts(db: Session, *, source: Cart, target: Cart) -> None:
    """Fold a guest cart into a shopper's cart. Quantities sum on collision."""
    rows = db.execute(
        select(CartItem, ProductVariant)
        .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
        .where(CartItem.cart_id == source.id)
    ).all()
    for item, variant in rows:
        _upsert_line(
            db,
            cart_id=target.id,
            variant=variant,
            quantity_delta=item.quantity,
            added_from_list_id=item.added_from_list_id,
            added_from_list_name=item.added_from_list_name,
            added_from_index=item.added_from_index,
            item_coupon_code=item.item_coupon_code,
        )
    db.execute(delete(CartItem).where(CartItem.cart_id == source.id))
    source.status = CartStatus.expired.value
    source.item_count = 0
    source.subtotal = ZERO
    source.discount_total = ZERO
    source.total = ZERO
    _record_mutation(db, cart=target, mutation_type="merge")
    _recalculate(db, target)


# --- attribution ----------------------------------------------------------


def _derive_channel(payload: dict) -> tuple[str, str, str | None, str]:
    """source / medium / campaign / channel_group from raw touch fields.

    Deliberately crude and deterministic. The point is that BI can group by a
    stable column; the nuanced model belongs to S5, which will extend this table
    rather than invent a second source of truth (section 4).
    """
    source = payload.get("utm_source")
    medium = payload.get("utm_medium")
    campaign = payload.get("utm_campaign")

    if not source:
        if payload.get("gclid") or payload.get("gbraid") or payload.get("wbraid"):
            source, medium = "google", medium or "cpc"
        elif payload.get("fbclid"):
            source, medium = "facebook", medium or "paid_social"
        elif payload.get("referrer"):
            source, medium = "referrer", medium or "referral"
        else:
            source, medium = "(direct)", medium or "(none)"

    medium = medium or "(none)"
    lowered = medium.lower()
    if lowered in {"cpc", "ppc", "paid", "paidsearch"}:
        group = "Paid Search"
    elif lowered in {"paid_social", "paid-social", "social_paid"}:
        group = "Paid Social"
    elif lowered in {"organic"}:
        group = "Organic Search"
    elif lowered in {"email"}:
        group = "Email"
    elif lowered in {"referral"}:
        group = "Referral"
    elif payload.get("affiliate_id"):
        group = "Affiliate"
    elif source == "(direct)":
        group = "Direct"
    else:
        group = "Other"
    return source, medium, campaign, group


def _apply_attribution(db: Session, cart: Cart, payload: dict | None) -> None:
    """Link/create the visitor, append a touch, and update the cart's carrier row.

    First touch is set once and never overwritten — section 11A's "never
    overwrite first acquisition", which is also acceptance criterion 7 (first
    touch survives a second visit through a different campaign).
    """
    if not payload:
        return

    visitor = None
    token = payload.get("visitor_token")
    if token:
        visitor = db.execute(
            select(AttributionVisitor).where(AttributionVisitor.visitor_token == token)
        ).scalar_one_or_none()
        if visitor is None:
            visitor = AttributionVisitor(
                visitor_token=token,
                ga_client_id=payload.get("ga_client_id"),
                first_landing_page=payload.get("landing_page"),
                first_referrer=payload.get("referrer"),
            )
            db.add(visitor)
            db.flush()
        else:
            visitor.last_seen_at = _now()
            if payload.get("ga_client_id") and not visitor.ga_client_id:
                visitor.ga_client_id = payload["ga_client_id"]

    touch = None
    if visitor is not None:
        source, medium, campaign, group = _derive_channel(payload)
        touch = AttributionTouch(
            visitor_id=visitor.id,
            utm_source=payload.get("utm_source"),
            utm_medium=payload.get("utm_medium"),
            utm_campaign=payload.get("utm_campaign"),
            utm_content=payload.get("utm_content"),
            utm_term=payload.get("utm_term"),
            utm_id=payload.get("utm_id"),
            gclid=payload.get("gclid"),
            gbraid=payload.get("gbraid"),
            wbraid=payload.get("wbraid"),
            fbclid=payload.get("fbclid"),
            fbp=payload.get("fbp"),
            fbc=payload.get("fbc"),
            ga_client_id=payload.get("ga_client_id"),
            ga_session_id=payload.get("ga_session_id"),
            affiliate_id=payload.get("affiliate_id"),
            referral_code=payload.get("referral_code"),
            coupon_code=payload.get("coupon_code"),
            landing_page=payload.get("landing_page"),
            referrer=payload.get("referrer"),
            locale=cart.locale,
            consent_state=payload.get("consent_state"),
            source=source,
            medium=medium,
            campaign=campaign,
            channel_group=group,
            extras=payload.get("extras") or {},
        )
        db.add(touch)
        db.flush()

    row = db.execute(
        select(CartAttribution).where(CartAttribution.cart_id == cart.id)
    ).scalar_one_or_none()
    if row is None:
        row = CartAttribution(cart_id=cart.id)
        db.add(row)

    if visitor is not None:
        row.visitor_id = visitor.id
    if touch is not None:
        if row.first_touch_id is None:
            row.first_touch_id = touch.id
        row.last_touch_id = touch.id
    row.updated_at = _now()
    db.flush()


# --- public API -----------------------------------------------------------


def create_or_get_cart(
    db: Session,
    *,
    locale: str,
    cart_token: str | None = None,
    claims: dict | None = None,
    attribution: dict | None = None,
) -> dict:
    """``POST /cart``. Returns the caller's active cart, creating one if needed.

    Creation is idempotent through the returned ``token`` rather than through an
    ``Idempotency-Key``: a caller who replays this without keeping the token
    genuinely has no cart to return, and issuing a fresh empty one is the only
    sane answer.
    """
    cart = _resolve(db, locale=locale, cart_token=cart_token, claims=claims, create=True)
    _apply_attribution(db, cart, attribution)
    _recalculate(db, cart)
    payload = _serialize(db, cart)
    db.commit()
    return payload


def get_cart(
    db: Session,
    *,
    locale: str,
    cart_token: str | None = None,
    claims: dict | None = None,
) -> dict:
    """``GET /cart``. 404 when the caller has no active cart."""
    cart = _resolve(
        db, locale=locale, cart_token=cart_token, claims=claims, create=False
    )
    payload = _serialize(db, cart)
    db.commit()
    return payload


def add_item(
    db: Session,
    *,
    locale: str,
    payload: dict,
    cart_token: str | None = None,
    claims: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """``POST /cart/items``.

    Creates the cart when the caller has none, so the first add does not require
    a prior ``POST /cart``. A cart token that resolves to nothing is still a 404
    — that is a client bug, not a new session.
    """
    if cart_token:
        cart = _resolve(
            db, locale=locale, cart_token=cart_token, claims=claims, create=False
        )
    else:
        cart = _resolve(
            db, locale=locale, cart_token=None, claims=claims, create=True
        )

    replay = _replayed(db, cart.id, idempotency_key)
    if replay is not None:
        result = _serialize(
            db, cart, replayed=True, logical_event_id=replay.logical_event_id
        )
        db.commit()
        return result

    variant = _load_variant(
        db, variant_id=payload.get("variant_id"), sku=payload.get("sku")
    )
    quantity = int(payload.get("quantity") or 1)
    _assert_purchasable(variant, quantity)

    new_quantity = _upsert_line(
        db,
        cart_id=cart.id,
        variant=variant,
        quantity_delta=quantity,
        added_from_list_id=payload.get("added_from_list_id"),
        added_from_list_name=payload.get("added_from_list_name"),
        added_from_index=payload.get("added_from_index"),
        item_coupon_code=payload.get("item_coupon_code"),
    )
    # Checked against the *resulting* quantity, so ten rapid adds of a
    # single-stock variant fail rather than accumulating an unfillable line.
    _assert_purchasable(variant, new_quantity)

    unit = _q(variant.sale_price if variant.sale_price is not None else variant.price)
    event_id = _record_mutation(
        db,
        cart=cart,
        mutation_type="add",
        idempotency_key=idempotency_key,
        variant_id=variant.id,
        quantity_delta=quantity,
        quantity_after=new_quantity,
        unit_price=unit,
        value_delta=unit * quantity,
    )
    _recalculate(db, cart)
    result = _serialize(db, cart, logical_event_id=event_id)
    db.commit()
    return result


def set_item_quantity(
    db: Session,
    *,
    locale: str,
    variant_id: int,
    quantity: int,
    cart_token: str | None = None,
    claims: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """``PATCH /cart/items/{variant_id}``. Absolute quantity; 0 removes.

    Absolute rather than a delta on purpose: a replayed delta doubles a basket,
    a replayed absolute set is a no-op even without the idempotency key.
    """
    cart = _resolve(
        db, locale=locale, cart_token=cart_token, claims=claims, create=False
    )

    replay = _replayed(db, cart.id, idempotency_key)
    if replay is not None:
        result = _serialize(
            db, cart, replayed=True, logical_event_id=replay.logical_event_id
        )
        db.commit()
        return result

    item = db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id, CartItem.variant_id == variant_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="item not in cart"
        )

    previous = item.quantity
    unit = _q(
        item.unit_sale_price_snapshot
        if item.unit_sale_price_snapshot is not None
        else item.unit_price_snapshot
    )

    if quantity == 0:
        db.execute(delete(CartItem).where(CartItem.id == item.id))
        mutation_type, after = "remove", 0
    else:
        variant = _load_variant(db, variant_id=variant_id, sku=None)
        _assert_purchasable(variant, quantity)
        item.quantity = quantity
        item.updated_at = _now()
        mutation_type, after = "update_quantity", quantity

    delta = after - previous
    event_id = _record_mutation(
        db,
        cart=cart,
        mutation_type=mutation_type,
        idempotency_key=idempotency_key,
        variant_id=variant_id,
        quantity_delta=delta,
        quantity_after=after,
        unit_price=unit,
        value_delta=unit * delta,
    )
    _recalculate(db, cart)
    result = _serialize(db, cart, logical_event_id=event_id)
    db.commit()
    return result


def remove_item(
    db: Session,
    *,
    locale: str,
    variant_id: int,
    cart_token: str | None = None,
    claims: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """``DELETE /cart/items/{variant_id}``."""
    return set_item_quantity(
        db,
        locale=locale,
        variant_id=variant_id,
        quantity=0,
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


def set_coupon(
    db: Session,
    *,
    locale: str,
    code: str | None,
    cart_token: str | None = None,
    claims: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """``POST /cart/coupon``. A null or empty code removes the current one.

    S1 has no promotions table (it is not in the design's table inventory), so
    this records the shopper's intent — the code is stored on the cart, carried
    into the order and available to ``attribution_touches.coupon_code`` — and
    does **not** move money. Inventing a discount rule here would put a second,
    unauditable pricing engine next to the money model.
    """
    cart = _resolve(
        db, locale=locale, cart_token=cart_token, claims=claims, create=False
    )

    replay = _replayed(db, cart.id, idempotency_key)
    if replay is not None:
        result = _serialize(
            db, cart, replayed=True, logical_event_id=replay.logical_event_id
        )
        db.commit()
        return result

    normalized = (code or "").strip().upper() or None
    if normalized is not None and not _COUPON_RE.match(normalized):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="invalid coupon code format",
        )

    if normalized == cart.coupon_code:
        # Applying the code already on the cart changes nothing, with or without
        # an idempotency key.
        result = _serialize(db, cart, replayed=True)
        db.commit()
        return result

    cart.coupon_code = normalized
    event_id = _record_mutation(
        db,
        cart=cart,
        mutation_type="apply_coupon" if normalized else "remove_coupon",
        idempotency_key=idempotency_key,
    )
    _recalculate(db, cart)
    result = _serialize(db, cart, logical_event_id=event_id)
    db.commit()
    return result


def reprice_cart(
    db: Session,
    *,
    locale: str,
    cart_token: str | None = None,
    claims: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """``POST /cart/reprice``. Adopt current catalog prices for drifted lines.

    The drift itself is always visible on a cart read (``price_changed``); this
    is the explicit act of accepting it. Nothing reprices implicitly, because a
    basket whose total moves without the shopper doing anything is the defect
    section 8 calls a price mismatch.
    """
    cart = _resolve(
        db, locale=locale, cart_token=cart_token, claims=claims, create=False
    )

    replay = _replayed(db, cart.id, idempotency_key)
    if replay is not None:
        result = _serialize(
            db, cart, replayed=True, logical_event_id=replay.logical_event_id
        )
        db.commit()
        return result

    rows = db.execute(
        select(CartItem, ProductVariant)
        .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
        .where(CartItem.cart_id == cart.id)
    ).all()

    before = _q(cart.total)
    changed = 0
    now = _now()
    for item, variant in rows:
        if (
            item.unit_price_snapshot == variant.price
            and item.unit_sale_price_snapshot == variant.sale_price
        ):
            continue
        item.unit_price_snapshot = variant.price
        item.unit_sale_price_snapshot = variant.sale_price
        item.price_snapshot_at = now
        item.last_repriced_at = now
        item.updated_at = now
        changed += 1

    if changed == 0:
        result = _serialize(db, cart, replayed=True)
        db.commit()
        return result

    _recalculate(db, cart)
    event_id = _record_mutation(
        db,
        cart=cart,
        mutation_type="reprice",
        idempotency_key=idempotency_key,
        quantity_after=cart.item_count,
        value_delta=_q(cart.total) - before,
    )
    result = _serialize(db, cart, logical_event_id=event_id)
    db.commit()
    return result


def attach_attribution(
    db: Session,
    *,
    locale: str,
    attribution: dict,
    cart_token: str | None = None,
    claims: dict | None = None,
) -> dict:
    """``POST /cart/attribution``.

    Section 4 requires the cart to be the durable carrier of acquisition data
    *before* an order exists, so the order snapshot can be built server-side at
    checkout even if the browser has lost everything. Creates the cart if the
    caller has none: a landing touch usually arrives before the first add.
    """
    cart = _resolve(db, locale=locale, cart_token=cart_token, claims=claims, create=True)
    _apply_attribution(db, cart, attribution)
    _touch(cart)
    payload = _serialize(db, cart)
    db.commit()
    return payload
