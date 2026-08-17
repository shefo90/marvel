"""Idempotent order creation â€” the piece section 2 and section 15 exist to make
correct.

Everything below happens inside **one** transaction, committed exactly once at
the end of :func:`create_order`. That is not a style choice:

* The ``idempotency_keys`` row is inserted in the same transaction as the work,
  so there is no window in which the key exists but the order does not. If the
  work raises, the claim disappears with it and the key is free to retry.
* The order number is allocated once, from the ``orders`` id sequence, before
  the INSERT. ``orders.order_number`` carries a BEFORE UPDATE trigger that
  raises on change, so there is no "insert a placeholder and fix it up" path â€”
  by construction, section 2's "never regenerate on refresh" cannot be violated.
* Every snapshot (attribution, catalog line, COGS, address) is **copied**, never
  joined at read time. A campaign rename, a price edit or a product archive
  after the fact must not move a placed order's numbers.

**What this module deliberately does not do**

* It never writes ``order_audit_log`` rows. The database trigger from migration
  0002 owns that, and creation is an INSERT anyway (the trigger is AFTER UPDATE).
  Where a future staff-driven correction needs attribution, it sets
  ``app.actor_user_id`` / ``app.audit_reason`` / ``app.audit_source`` with
  ``SET LOCAL`` in the same transaction and lets the trigger read them.
* It never caches. Orders, carts and customers are per-shopper mutable state;
  a shared cache is how one shopper sees another's order.
* It trusts no money from the client. Totals are recomputed from the
  server-side cart lines, and the line prices are re-checked against the live
  variant before the order is written.

**Money posture.** Prices are VAT-inclusive (design section 2), so ``tax_total``
is 0 and the ``ck_orders_total_identity`` CHECK holds as
``total = subtotal - discount + 0 + shipping``. ``gross_order_value`` is set to
``total`` at creation and frozen â€” it is section 11's "Gross ordered revenue"
and must not drift when refunds later move ``total``'s neighbours.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Date, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.config import IDEMPOTENCY_TTL_HOURS, ORDER_NUMBER_PREFIX
from core.enums import (
    ActorType,
    CartStatus,
    CodCollectionStatus,
    IdentitySource,
    IdentityType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from models.attribution_touches import AttributionTouch
from models.attribution_visitors import AttributionVisitor
from models.cart_attributions import CartAttribution
from models.cart_items import CartItem
from models.carts import Cart
from models.categories import Category
from models.customer_attributions import CustomerAttribution
from models.customer_identity import CustomerIdentity
from models.customers import Customer
from models.idempotency_keys import IdempotencyKey
from models.locales import Locale
from models.order_addresses import OrderAddress
from models.order_attributions import OrderAttribution
from models.order_items import OrderItem
from models.order_status_history import OrderStatusHistory
from models.orders import Order
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from schema.order import order_create_request
from services import identity

# Namespaced so an order key can never collide with an S4 webhook key.
IDEMPOTENCY_SCOPE = "order_create"

CENT = Decimal("0.01")


# --- Small pure helpers ---------------------------------------------------
def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(payload: dict) -> str:
    """Canonical hash of the request body.

    Key order and whitespace must not change the fingerprint, or a retry from a
    different HTTP client would look like a different request and 409.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256(canonical)


# Delegated to services.identity â€” the SINGLE implementation. Checkout and
# registration must normalize identically or the same shopper resolves to two
# customer_identity rows and two customers, silently corrupting section 11A's
# new-vs-returning classification and every lifetime aggregate. These two files
# previously disagreed on phone format; do not reintroduce a local copy.
_normalize_email = identity.normalize_email
_normalize_phone = identity.normalize_phone


def _variant_effective_price(price, sale_price) -> Decimal:
    return _money(sale_price if sale_price is not None else price)


# --- Locale ---------------------------------------------------------------
def resolve_locale(db: Session, locale: str) -> str:
    """Reject unknown locale segments (section 8A forbids soft-404s)."""
    row = db.execute(
        select(Locale).where(Locale.code == locale, Locale.is_active.is_(True))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown locale")
    return locale


# --- Customer resolution --------------------------------------------------
def _identity_owner(
    db: Session,
    identity_type: IdentityType,
    value: str,
    customer_id: int,
    now: datetime,
) -> int:
    """Race-safe claim of a deterministic match key.

    ``INSERT ... ON CONFLICT (identity_type, value_normalized) DO UPDATE``
    returns the *winning* customer id, so two concurrent guest checkouts with
    the same email cannot create two customers: the loser's insert conflicts and
    it learns whose row it is. ``customer_id`` is never repointed on conflict â€”
    reassigning an identity to another customer is a merge, and merges have
    their own audited table (section 11A's "explicit, auditable rules").
    """
    has_primary = db.execute(
        select(CustomerIdentity.id).where(
            CustomerIdentity.customer_id == customer_id,
            CustomerIdentity.identity_type == identity_type,
            CustomerIdentity.is_primary.is_(True),
        )
    ).first()

    stmt = (
        pg_insert(CustomerIdentity)
        .values(
            customer_id=customer_id,
            identity_type=identity_type.value,
            value_normalized=value,
            value_sha256=_sha256(value),
            source=IdentitySource.order.value,
            is_primary=has_primary is None,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=["identity_type", "value_normalized"],
            set_={"last_seen_at": now},
        )
        .returning(CustomerIdentity.customer_id)
    )
    return db.execute(stmt).scalar_one()


def _resolve_customer(
    db: Session, contact, now: datetime
) -> Customer:
    """Find or create the shopper. No login required â€” guest checkout is a
    first-class path (section 2), but a ``customers`` row exists for every order
    so section 11A's customer layer is never missing a purchaser."""
    email = _normalize_email(contact.email)
    phone = _normalize_phone(contact.phone)
    if not email and not phone:
        raise HTTPException(
            status_code=400, detail="customer email or phone is required"
        )

    lookups = []
    if email:
        lookups.append((IdentityType.email, email))
    if phone:
        lookups.append((IdentityType.phone, phone))

    customer: Customer | None = None
    for identity_type, value in lookups:
        owner_id = db.execute(
            select(CustomerIdentity.customer_id).where(
                CustomerIdentity.identity_type == identity_type,
                CustomerIdentity.value_normalized == value,
            )
        ).scalar_one_or_none()
        if owner_id is not None:
            customer = db.get(Customer, owner_id)
            break

    if customer is None:
        customer = Customer(
            email=email,
            phone=phone,
            first_name=contact.first_name,
            last_name=contact.last_name,
        )
        db.add(customer)
        db.flush()

        # The primary identity decides who wins a concurrent first checkout.
        primary_type, primary_value = lookups[0]
        owner_id = _identity_owner(db, primary_type, primary_value, customer.id, now)
        if owner_id != customer.id:
            # Someone else created this shopper microseconds ago. Adopt theirs
            # and drop ours; nothing references it yet.
            db.delete(customer)
            db.flush()
            customer = db.get(Customer, owner_id)
        # The primary identity is claimed either way â€” inserted by us, or its
        # last_seen_at refreshed on the row that beat us to it.
        lookups = lookups[1:]
    else:
        if email and not customer.email:
            customer.email = email
        if phone and not customer.phone:
            customer.phone = phone
        if contact.first_name and not customer.first_name:
            customer.first_name = contact.first_name
        if contact.last_name and not customer.last_name:
            customer.last_name = contact.last_name

    for identity_type, value in lookups:
        # A secondary identity already owned by a different customer is left
        # exactly where it is. Silently repointing it would merge two shoppers
        # with no audit trail.
        _identity_owner(db, identity_type, value, customer.id, now)

    return customer


# --- Attribution ----------------------------------------------------------
def _touch_fields(touch: AttributionTouch | None, prefix: str) -> dict:
    if touch is None:
        return {}
    return {
        f"{prefix}_at": touch.occurred_at,
        f"{prefix}_source": touch.source or touch.utm_source,
        f"{prefix}_medium": touch.medium or touch.utm_medium,
        f"{prefix}_campaign": touch.campaign or touch.utm_campaign,
        f"{prefix}_channel_group": touch.channel_group,
        f"{prefix}_landing_page": touch.landing_page,
    }


def _snapshot_attribution(
    db: Session, order: Order, cart: Cart, customer: Customer, locale: str, now: datetime
) -> OrderAttribution:
    """Copy the cart's acquisition history onto the order, and preserve the
    customer's first touch.

    Section 11A: "Do not overwrite first acquisition when a returning customer
    comes through a new campaign." ``first_touch_locked_at`` is the lock, and it
    is only ever stamped together with ``first_touch_id`` â€” the CHECK constraint
    requires the two to agree.
    """
    cart_attr = db.get(CartAttribution, cart.id)
    first_touch = last_touch = None
    visitor = None
    if cart_attr is not None:
        if cart_attr.first_touch_id:
            first_touch = db.get(AttributionTouch, cart_attr.first_touch_id)
        if cart_attr.last_touch_id:
            last_touch = db.get(AttributionTouch, cart_attr.last_touch_id)
        if cart_attr.visitor_id:
            visitor = db.get(AttributionVisitor, cart_attr.visitor_id)

    values = {
        "order_id": order.id,
        "locale": locale,
        "coupon_code": cart.coupon_code,
        "snapshot_at": now,
        "extras": {},
    }
    # First and last touch are populated separately â€” an order acquired by
    # organic search and converted through a paid remarketing click must keep
    # both facts.
    values.update(_touch_fields(first_touch, "first_touch"))
    values.update(_touch_fields(last_touch, "last_touch"))

    # Conversion-time identifiers come from the last touch: they are what the
    # ad platforms will match on when S5 uploads the offline conversion.
    if last_touch is not None:
        for column in (
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "utm_id",
            "gclid",
            "gbraid",
            "wbraid",
            "fbclid",
            "fbp",
            "fbc",
            "ga_client_id",
            "ga_session_id",
            "affiliate_id",
            "referral_code",
            "landing_page",
            "referrer",
            "consent_state",
        ):
            values[column] = getattr(last_touch, column)
        values["coupon_code"] = cart.coupon_code or last_touch.coupon_code
        values["extras"] = dict(last_touch.extras or {})
    if visitor is not None:
        values["visitor_token"] = visitor.visitor_token
        if not values.get("ga_client_id"):
            values["ga_client_id"] = visitor.ga_client_id

    snapshot = OrderAttribution(**values)
    db.add(snapshot)

    # --- Customer-level attribution: first touch is write-once -------------
    customer_attr = db.get(CustomerAttribution, customer.id)
    if customer_attr is None:
        customer_attr = CustomerAttribution(customer_id=customer.id)
        db.add(customer_attr)
        db.flush()

    if customer_attr.first_touch_locked_at is None and first_touch is not None:
        customer_attr.first_touch_id = first_touch.id
        customer_attr.first_touch_at = first_touch.occurred_at
        customer_attr.first_touch_locked_at = now
        customer_attr.first_touch_source = first_touch.source or first_touch.utm_source
        customer_attr.first_touch_medium = first_touch.medium or first_touch.utm_medium
        customer_attr.first_touch_campaign = (
            first_touch.campaign or first_touch.utm_campaign
        )
        customer_attr.first_touch_channel_group = first_touch.channel_group

    if last_touch is not None:
        customer_attr.last_touch_id = last_touch.id
        customer_attr.last_touch_at = last_touch.occurred_at
        customer_attr.last_touch_source = last_touch.source or last_touch.utm_source
        customer_attr.last_touch_medium = last_touch.medium or last_touch.utm_medium
        customer_attr.last_touch_campaign = (
            last_touch.campaign or last_touch.utm_campaign
        )
        customer_attr.last_touch_channel_group = last_touch.channel_group

    return snapshot


# --- Line snapshots -------------------------------------------------------
def _category_path(db: Session, product: Product) -> str | None:
    category = db.get(Category, product.category_id) if product.category_id else None
    if category is None:
        return None
    parent = db.get(Category, category.parent_id) if category.parent_id else None
    return f"{parent.name} > {category.name}" if parent else category.name


def _build_lines(db: Session, cart: Cart, locale: str) -> list[dict]:
    """Snapshot every cart line, including its COGS.

    Section 11A: COGS is captured here and never recalculated from today's cost.
    When the variant has no cost, ``unit_cogs`` stays NULL and the source is
    recorded as ``unknown`` so a missing margin is distinguishable from a
    genuinely zero one.
    """
    cart_items = (
        db.execute(
            select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
        )
        .scalars()
        .all()
    )
    if not cart_items:
        raise HTTPException(status_code=400, detail="cart is empty")

    lines: list[dict] = []
    for line_number, item in enumerate(cart_items, start=1):
        variant = db.get(ProductVariant, item.variant_id)
        if variant is None or not variant.is_active:
            raise HTTPException(
                status_code=409, detail=f"variant {item.sku} is no longer available"
            )
        if variant.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"insufficient stock for {variant.sku}",
            )

        live_price = _variant_effective_price(variant.price, variant.sale_price)
        cart_price = _variant_effective_price(
            item.unit_price_snapshot, item.unit_sale_price_snapshot
        )
        if live_price != cart_price:
            # The cart line docstring's contract: a price change between adding
            # and paying is surfaced, never silently applied.
            raise HTTPException(
                status_code=409,
                detail=f"price changed for {variant.sku}; refresh the cart",
            )

        product = db.get(Product, variant.product_id)
        translation = db.execute(
            select(ProductTranslation).where(
                ProductTranslation.product_id == product.id,
                ProductTranslation.locale == locale,
                ProductTranslation.is_published.is_(True),
            )
        ).scalar_one_or_none()

        title = translation.title if translation else product.title
        slug = translation.slug if translation else product.slug

        attributes = dict(variant.attributes or {})
        for key in ("size", "color", "material"):
            value = getattr(variant, key)
            if value is not None:
                attributes.setdefault(key, value)
        if variant.size_system:
            attributes.setdefault("size_system", variant.size_system)

        quantity = item.quantity
        line_subtotal = (live_price * quantity).quantize(CENT)
        discount_amount = Decimal("0.00")
        line_total = (line_subtotal - discount_amount).quantize(CENT)

        has_cost = variant.cost is not None
        unit_cogs = _money(variant.cost) if has_cost else None
        line_cogs = (unit_cogs * quantity).quantize(CENT) if has_cost else None

        lines.append(
            {
                "line_number": line_number,
                "product_id": product.id,
                "variant_id": variant.id,
                "sku": variant.sku,
                "item_group_id": product.item_group_id,
                "product_title": title,
                "variant_label": variant.variant_title,
                "variant_attributes": attributes,
                "brand": product.brand,
                "category_path": _category_path(db, product),
                "product_url": f"/{locale}/products/{slug}",
                "item_list_id": item.added_from_list_id,
                "item_list_name": item.added_from_list_name,
                "unit_list_price": _money(variant.price),
                "unit_price": live_price,
                "quantity": quantity,
                "discount_amount": discount_amount,
                "coupon_code": item.item_coupon_code,
                "line_subtotal": line_subtotal,
                "tax_amount": Decimal("0.00"),
                "line_total": line_total,
                "unit_cogs": unit_cogs,
                "line_cogs": line_cogs,
                # 'unknown' is load-bearing: it says the margin cannot be
                # computed, rather than that it is zero.
                "cogs_snapshot_source": "variant_cost" if has_cost else "unknown",
            }
        )
    return lines


# --- Response payload -----------------------------------------------------
def _order_payload(db: Session, order: Order) -> dict:
    """Fully-serialized order, JSON-safe.

    JSON-safe matters twice over: this is both the HTTP response and the body
    stored in ``idempotency_keys.response_body`` for verbatim replay.
    """
    items = (
        db.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.line_number)
        )
        .scalars()
        .all()
    )
    address = db.execute(
        select(OrderAddress).where(
            OrderAddress.order_id == order.id,
            OrderAddress.address_type == "shipping",
            OrderAddress.superseded_at.is_(None),
        )
    ).scalar_one_or_none()
    attribution = db.get(OrderAttribution, order.id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None

    def enum_value(value):
        return value.value if hasattr(value, "value") else value

    def num(value):
        return str(_money(value)) if value is not None else None

    return {
        "order_number": order.order_number,
        "status": enum_value(order.status),
        "locale": order.locale,
        "currency": order.currency,
        # Opaque UUID only â€” section 2 keeps customers.id off the browser.
        "customer_public_id": str(customer.public_id) if customer else None,
        "is_new_customer": order.is_new_customer,
        "subtotal": num(order.subtotal),
        "discount": num(order.discount),
        "tax_total": num(order.tax_total),
        "shipping": num(order.shipping),
        "total": num(order.total),
        "gross_order_value": num(order.gross_order_value),
        "items_cogs_total": num(order.items_cogs_total),
        "coupon_code": order.coupon_code,
        "payment_status": enum_value(order.payment_status),
        "payment_method": enum_value(order.payment_method),
        "payment_provider": order.payment_provider,
        "cod_amount": num(order.cod_amount),
        "cod_collection_status": enum_value(order.cod_collection_status),
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "business_date": order.business_date.isoformat()
        if order.business_date
        else None,
        "items": [
            {
                "line_number": i.line_number,
                "sku": i.sku,
                "item_group_id": i.item_group_id,
                "product_title": i.product_title,
                "variant_label": i.variant_label,
                "variant_attributes": dict(i.variant_attributes or {}),
                "brand": i.brand,
                "category_path": i.category_path,
                "product_url": i.product_url,
                "item_list_id": i.item_list_id,
                "item_list_name": i.item_list_name,
                "unit_list_price": num(i.unit_list_price),
                "unit_price": num(i.unit_price),
                "quantity": i.quantity,
                "discount_amount": num(i.discount_amount),
                "line_subtotal": num(i.line_subtotal),
                "tax_amount": num(i.tax_amount),
                "line_total": num(i.line_total),
                "unit_cogs": num(i.unit_cogs),
                "line_cogs": num(i.line_cogs),
                "cogs_snapshot_source": i.cogs_snapshot_source,
            }
            for i in items
        ],
        "shipping_address": {
            "address_type": enum_value(address.address_type),
            "recipient_name": address.recipient_name,
            "phone": address.phone,
            "phone_alt": address.phone_alt,
            "governorate": address.governorate,
            "city": address.city,
            "district": address.district,
            "street_address": address.street_address,
            "building": address.building,
            "floor": address.floor,
            "apartment": address.apartment,
            "landmark": address.landmark,
            "postal_code": address.postal_code,
            "country_code": address.country_code,
        }
        if address
        else None,
        "attribution": {
            "first_touch_at": attribution.first_touch_at.isoformat()
            if attribution.first_touch_at
            else None,
            "first_touch_source": attribution.first_touch_source,
            "first_touch_medium": attribution.first_touch_medium,
            "first_touch_campaign": attribution.first_touch_campaign,
            "first_touch_channel_group": attribution.first_touch_channel_group,
            "first_touch_landing_page": attribution.first_touch_landing_page,
            "last_touch_at": attribution.last_touch_at.isoformat()
            if attribution.last_touch_at
            else None,
            "last_touch_source": attribution.last_touch_source,
            "last_touch_medium": attribution.last_touch_medium,
            "last_touch_campaign": attribution.last_touch_campaign,
            "last_touch_channel_group": attribution.last_touch_channel_group,
            "last_touch_landing_page": attribution.last_touch_landing_page,
            "utm_source": attribution.utm_source,
            "utm_medium": attribution.utm_medium,
            "utm_campaign": attribution.utm_campaign,
            "utm_content": attribution.utm_content,
            "utm_term": attribution.utm_term,
            "utm_id": attribution.utm_id,
            "gclid": attribution.gclid,
            "gbraid": attribution.gbraid,
            "wbraid": attribution.wbraid,
            "fbclid": attribution.fbclid,
            "fbp": attribution.fbp,
            "fbc": attribution.fbc,
            "ga_client_id": attribution.ga_client_id,
            "ga_session_id": attribution.ga_session_id,
            "affiliate_id": attribution.affiliate_id,
            "referral_code": attribution.referral_code,
            "coupon_code": attribution.coupon_code,
            "landing_page": attribution.landing_page,
            "referrer": attribution.referrer,
            "locale": attribution.locale,
            "visitor_token": attribution.visitor_token,
            "extras": dict(attribution.extras or {}),
        }
        if attribution
        else None,
    }


# --- The write path -------------------------------------------------------
def _business_date(db: Session) -> date:
    """Reporting date in the business timezone; timestamps stay UTC.

    Computed by Postgres rather than Python because the container has no tz
    database, and a business date that silently falls back to UTC would move
    every late-evening Cairo order into the previous day.
    """
    return db.execute(
        select(cast(func.timezone("Africa/Cairo", func.now()), Date))
    ).scalar_one()


def _create(
    db: Session, locale: str, payload: order_create_request, now: datetime
) -> tuple[dict, int]:
    cart = db.execute(
        select(Cart).where(Cart.token == payload.cart_token)
    ).scalar_one_or_none()
    if cart is None:
        raise HTTPException(status_code=404, detail="cart not found")
    cart_status = (
        cart.status.value if hasattr(cart.status, "value") else str(cart.status)
    )
    if cart_status == CartStatus.converted.value:
        raise HTTPException(status_code=409, detail="cart has already been converted")
    if cart_status != CartStatus.active.value:
        raise HTTPException(status_code=409, detail=f"cart is {cart_status}")

    lines = _build_lines(db, cart, locale)
    customer = _resolve_customer(db, payload.customer, now)

    # Section 6: new-vs-returning from authoritative order history, never from a
    # client flag or a browser cookie.
    prior_orders = db.execute(
        select(func.count())
        .select_from(Order)
        .where(Order.customer_id == customer.id)
    ).scalar_one()

    subtotal = sum((line["line_subtotal"] for line in lines), Decimal("0.00")).quantize(
        CENT
    )
    discount = _money(cart.discount_total)
    if discount > subtotal:
        raise HTTPException(status_code=409, detail="cart discount exceeds subtotal")
    # S1 has no shipping-rate engine: quoting arrives with the courier adapter in
    # S4, and inventing a rate here would put a fabricated number into section
    # 11's revenue. VAT is inclusive, so tax_total is 0 by design.
    shipping = Decimal("0.00")
    tax_total = Decimal("0.00")
    total = (subtotal - discount + tax_total + shipping).quantize(CENT)
    items_cogs_total = sum(
        (line["line_cogs"] for line in lines if line["line_cogs"] is not None),
        Decimal("0.00"),
    ).quantize(CENT)

    method = payload.payment_method
    is_cod = method == PaymentMethod.cod

    # Section 2: allocate the identity once, before the row exists. The id
    # sequence is already unique and monotonic, so no second sequence and no
    # read-modify-write on a counter table.
    order_id = db.execute(
        text("SELECT nextval(pg_get_serial_sequence('orders','id'))")
    ).scalar_one()
    order_number = f"{ORDER_NUMBER_PREFIX}-{order_id}"

    order = Order(
        id=order_id,
        order_number=order_number,
        customer_id=customer.id,
        cart_id=cart.id,
        status=OrderStatus.pending,
        locale=locale,
        currency="EGP",
        subtotal=subtotal,
        discount=discount,
        tax_total=tax_total,
        shipping=shipping,
        total=total,
        # Section 11's "Gross ordered revenue": frozen at creation.
        gross_order_value=total,
        coupon_code=cart.coupon_code,
        payment_status=PaymentStatus.pending,
        payment_method=method,
        payment_provider=payload.payment_provider,
        # The COD pair is present exactly when the method is cod â€” the
        # ck_orders_cod_fields_consistent CHECK rejects any other combination.
        cod_amount=total if is_cod else None,
        cod_collection_status=CodCollectionStatus.pending if is_cod else None,
        items_cogs_total=items_cogs_total,
        is_new_customer=prior_orders == 0,
        business_date=_business_date(db),
        placed_at=now,
    )
    db.add(order)
    db.flush()

    for line in lines:
        db.add(OrderItem(order_id=order.id, **line))

    _snapshot_attribution(db, order, cart, customer, locale, now)

    address = payload.shipping_address
    db.add(
        OrderAddress(
            order_id=order.id,
            address_type="shipping",
            recipient_name=address.recipient_name,
            phone=address.phone,
            phone_alt=address.phone_alt,
            governorate=address.governorate,
            city=address.city,
            district=address.district,
            street_address=address.street_address,
            building=address.building,
            floor=address.floor,
            apartment=address.apartment,
            landmark=address.landmark,
            postal_code=address.postal_code,
            country_code=address.country_code.upper(),
            captured_at=now,
        )
    )

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            dimension="order",
            from_status=None,
            to_status=OrderStatus.pending.value,
            actor_type=ActorType.customer,
            source="checkout",
            reason="order created",
            # Reused by S3/S5 as this transition's deduplication key.
            logical_event_id=f"{order_number}:order:pending",
            occurred_at=now,
        )
    )

    # Section 11A customer layer, from authoritative order history rather than
    # an ad-hoc increment driven by a browser event.
    customer.orders_count = prior_orders + 1
    customer.last_order_at = now
    if customer.first_order_at is None:
        customer.first_order_at = now
    customer.lifetime_gross_ordered_revenue = _money(
        customer.lifetime_gross_ordered_revenue
    ) + total

    # The cart's status and its converted_order_id must agree â€” there is a CHECK
    # that says so, which is what makes "converted but pointing nowhere"
    # unrepresentable.
    cart.status = CartStatus.converted
    cart.converted_order_id = order.id
    cart.converted_at = now
    cart.last_activity_at = now

    db.flush()
    return _order_payload(db, order), order.id


def create_order(
    db: Session,
    *,
    locale: str,
    idempotency_key: str | None,
    payload: order_create_request,
) -> tuple[int, dict, bool]:
    """Create an order, exactly once per idempotency key.

    Returns ``(http_status, body, replayed)``.

    The replay contract, in full:

    * **First request** â€” claims the key with ``status='in_progress'`` in the
      same transaction as the order, then stores the response and stamps
      ``completed_at`` before committing. Nothing is visible to another
      connection until all of it is.
    * **Replay, same body** â€” returns the stored status and body verbatim. It
      does not re-execute, which is what makes section 15's "Purchase fires once
      after refresh/back navigation and has stable transaction_id" true of the
      server and not merely of the browser.
    * **Replay, different body** â€” 409. The same key with a different payload is
      a client bug; serving the old response would hide it and quietly drop an
      order the shopper believes they placed.
    * **Concurrent duplicate** â€” the second INSERT blocks on the unique index
      until the first transaction resolves, then either replays its stored
      response or, if the first rolled back, proceeds itself. A row still marked
      ``in_progress`` can only be the debris of a crashed process, and gets a
      409 rather than a second order.
    * **Expired key** â€” past ``expires_at`` the row no longer protects anything
      (open question 5's retention window), so it is discarded and the key is
      claimed afresh.
    """
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=400, detail="Idempotency-Key header is required"
        )
    if len(key) > 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key is too long")

    fingerprint = _fingerprint(payload.model_dump(mode="json"))
    now = datetime.now(timezone.utc)

    def claim() -> int | None:
        stmt = (
            pg_insert(IdempotencyKey)
            .values(
                scope=IDEMPOTENCY_SCOPE,
                key=key,
                status="in_progress",
                request_fingerprint=fingerprint,
                created_at=now,
                expires_at=now + timedelta(hours=IDEMPOTENCY_TTL_HOURS),
            )
            .on_conflict_do_nothing(index_elements=["scope", "key"])
            .returning(IdempotencyKey.id)
        )
        return db.execute(stmt).scalar_one_or_none()

    claim_id = claim()
    if claim_id is None:
        existing = db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == IDEMPOTENCY_SCOPE, IdempotencyKey.key == key
            )
        ).scalar_one()

        if existing.expires_at is not None and existing.expires_at <= now:
            db.delete(existing)
            db.flush()
            claim_id = claim()
            if claim_id is None:  # pragma: no cover - lost a race for the key
                db.rollback()
                raise HTTPException(
                    status_code=409, detail="order creation already in progress"
                )
        elif existing.request_fingerprint != fingerprint:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used with a different request body",
            )
        elif existing.status == "completed":
            body = existing.response_body
            status_code = existing.response_status or 200
            db.rollback()
            return status_code, body, True
        elif existing.status == "in_progress":
            db.rollback()
            raise HTTPException(
                status_code=409, detail="order creation already in progress"
            )
        else:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=existing.last_error or "previous attempt with this key failed",
            )

    try:
        body, order_id = _create(db, locale=locale, payload=payload, now=now)
    except Exception:
        # The claim row was written in this transaction, so it rolls back too and
        # the key is free for an honest retry.
        db.rollback()
        raise

    db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == claim_id)
        .values(
            status="completed",
            response_status=201,
            response_body=body,
            order_id=order_id,
            completed_at=now,
        )
    )
    db.commit()
    return 201, body, False


# --- Read -----------------------------------------------------------------
def get_order(
    db: Session,
    *,
    order_number: str,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Look up one order by its section 2 identifier.

    Order numbers are sequential and therefore guessable, so a bare lookup would
    hand anyone the shopper's address and phone. The caller must present the
    email or phone the order was placed with; a mismatch returns 404 rather than
    403, so the endpoint does not confirm which order numbers exist.

    Never cached â€” orders are per-shopper mutable state (section 13 read
    through, not around, the database).
    """
    order = db.execute(
        select(Order).where(Order.order_number == order_number)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")

    if order.customer_id is not None:
        candidates = [
            v
            for v in (_normalize_email(email), _normalize_phone(phone))
            if v is not None
        ]
        if not candidates:
            raise HTTPException(
                status_code=400,
                detail="email or phone is required to look up an order",
            )
        match = db.execute(
            select(CustomerIdentity.id).where(
                CustomerIdentity.customer_id == order.customer_id,
                CustomerIdentity.value_normalized.in_(candidates),
            )
        ).first()
        if match is None:
            raise HTTPException(status_code=404, detail="order not found")

    return _order_payload(db, order)

