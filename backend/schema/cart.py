"""Server-side cart contracts.

Zero logic — Pydantic models only.

Three things in here exist because of the spec rather than because of the UI:

* ``added_from_list_id`` / ``added_from_list_name`` / ``added_from_index`` are
  section 5's ``item_list_id`` / ``item_list_name`` / ``index``. They describe the
  *surface* the shopper selected from and are impossible to reconstruct later, so
  the add-to-cart request must carry them and the cart line must store them. They
  are copied onto ``order_items`` at conversion.
* ``unit_price_snapshot`` / ``unit_sale_price_snapshot`` are the price at add
  time. Cart totals are computed from the snapshot, never from today's catalog
  price, so a price edit mid-session is *detected* (``price_changed``) rather
  than silently applied.
* the attribution block is section 4: the cart is the durable carrier of
  acquisition data before an order exists, so the history survives browser loss.

``token`` is the anonymous cart identity. It is opaque and carries no PII, so
returning it to the browser is fine — it is the thing that makes a guest cart
survive a lost cookie. The internal ``customers.id`` is deliberately absent.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# --- Requests -------------------------------------------------------------


class attribution_input(BaseModel):
    """Section 4's channel-neutral touch, as the browser can supply it.

    Every field is optional: a direct visit with consent denied legitimately
    produces a touch with nothing but a landing page.
    """

    visitor_token: str | None = Field(None, max_length=64)
    ga_client_id: str | None = Field(None, max_length=64)
    ga_session_id: str | None = Field(None, max_length=64)

    utm_source: str | None = Field(None, max_length=255)
    utm_medium: str | None = Field(None, max_length=255)
    utm_campaign: str | None = Field(None, max_length=255)
    utm_content: str | None = Field(None, max_length=255)
    utm_term: str | None = Field(None, max_length=255)
    utm_id: str | None = Field(None, max_length=255)

    gclid: str | None = Field(None, max_length=255)
    gbraid: str | None = Field(None, max_length=255)
    wbraid: str | None = Field(None, max_length=255)
    fbclid: str | None = Field(None, max_length=255)
    fbp: str | None = Field(None, max_length=255)
    fbc: str | None = Field(None, max_length=255)

    affiliate_id: str | None = Field(None, max_length=128)
    referral_code: str | None = Field(None, max_length=128)
    coupon_code: str | None = Field(None, max_length=64)

    landing_page: str | None = None
    referrer: str | None = None
    # Section 12: the consent state in force when the touch was recorded.
    consent_state: dict | None = None
    # Channels that are not enabled yet (ttclid, sc_click_id, msclkid, ...).
    extras: dict = {}


class cart_create_request(BaseModel):
    """Body of ``POST /cart``. Everything is optional — an empty body is a
    perfectly valid "give me a cart"."""

    attribution: attribution_input | None = None


class cart_item_add_request(BaseModel):
    """Either ``variant_id`` or ``sku`` identifies the line.

    Both are accepted because ``sku`` is section 2's sellable identity (the same
    string GA4 sends as ``item_id``), so a frontend that only ever handled SKUs
    should not have to look an id up first.
    """

    variant_id: int | None = None
    sku: str | None = Field(None, max_length=64)
    quantity: int = Field(1, ge=1, le=99)

    # Section 5 list attribution, captured at the moment of the add.
    added_from_list_id: str | None = Field(None, max_length=64)
    added_from_list_name: str | None = Field(None, max_length=160)
    added_from_index: int | None = Field(None, ge=0)
    item_coupon_code: str | None = Field(None, max_length=64)


class cart_item_quantity_request(BaseModel):
    """``PATCH /cart/items/{variant_id}``. Absolute quantity, not a delta —
    a delta cannot be replayed safely, an absolute value can. Zero removes."""

    quantity: int = Field(..., ge=0, le=99)


class cart_coupon_request(BaseModel):
    """``POST /cart/coupon``. A null or empty code removes the current one."""

    code: str | None = Field(None, max_length=64)


class cart_attribution_request(BaseModel):
    attribution: attribution_input


# --- Responses ------------------------------------------------------------


class cart_item_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    # Section 2: the sellable identity. Same string as GA4/Ads item_id.
    sku: str
    product_id: int | None = None
    title: str | None = None
    quantity: int

    unit_price_snapshot: Decimal
    unit_sale_price_snapshot: Decimal | None = None
    unit_price_effective: Decimal
    line_total: Decimal
    line_discount: Decimal
    # Which offer priced this line, if any. The storefront needs it to say
    # "Eid 20% off" beside a price rather than an unexplained number.
    promotion_id: int | None = None
    discount_source: str | None = None

    price_snapshot_at: datetime
    last_repriced_at: datetime | None = None
    # True when the catalog price has moved since the snapshot was taken. The
    # cart still charges the snapshot until an explicit reprice.
    price_changed: bool = False
    current_unit_price: Decimal | None = None

    added_from_list_id: str | None = None
    added_from_list_name: str | None = None
    added_from_index: int | None = None
    item_coupon_code: str | None = None

    availability: str | None = None
    stock_quantity: int | None = None


class cart_attribution_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visitor_token: str | None = None
    # Section 11A: first touch is written once and never overwritten.
    first_touch_id: int | None = None
    last_touch_id: int | None = None
    first_touch_source: str | None = None
    first_touch_medium: str | None = None
    first_touch_campaign: str | None = None
    last_touch_source: str | None = None
    last_touch_medium: str | None = None
    last_touch_campaign: str | None = None


class cart_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Opaque anonymous identity. Not PII.
    token: str
    status: str
    locale: str
    currency: str = "EGP"

    item_count: int
    subtotal: Decimal
    discount_total: Decimal
    total: Decimal
    coupon_code: str | None = None

    items: list[cart_item_response] = []
    attribution: cart_attribution_response | None = None

    # Set when the request carried an Idempotency-Key that had already been
    # applied: the state is the original one and nothing was changed.
    replayed: bool = False
    # The id S3/S5 reuse to deduplicate the browser and server copies of this
    # event. Null when the request changed nothing.
    logical_event_id: str | None = None

    last_activity_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None
