"""Order contracts — request and response shapes only.

Zero logic: no validators, no derivation, no defaults that encode a business
rule. Everything the client could lie about is *ignored* rather than validated
here, which is why this file is so short on money fields:

* There is no ``subtotal``/``total`` input. Totals are recomputed in the
  repository from the server-side cart lines. A client-supplied total would be
  the single easiest way to poison section 11's revenue reporting.
* There is no ``is_new_customer`` input. Section 6 is explicit that new-vs-
  returning is derived from authoritative order history and never inferred from
  a browser flag.
* There is no ``order_number`` input. Section 2's transaction id is generated
  once, server-side, and is immutable thereafter.

The response carries ``customer_public_id`` (an opaque UUID) and never
``customers.id`` — section 2 keeps the internal customer id off the browser.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from core.enums import PaymentMethod


# --- Request -------------------------------------------------------------
class order_customer_input(BaseModel):
    """Guest or account shopper contact.

    At least one of email/phone must be present — enforced in the repository,
    because it is a rule about the pair rather than a shape constraint.
    """

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class order_address_input(BaseModel):
    """Shipping address as typed at checkout. Snapshotted write-once."""

    recipient_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=1, max_length=20)
    phone_alt: str | None = Field(default=None, max_length=20)
    governorate: str = Field(min_length=1, max_length=64)
    city: str = Field(min_length=1, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    street_address: str = Field(min_length=1)
    building: str | None = Field(default=None, max_length=50)
    floor: str | None = Field(default=None, max_length=20)
    apartment: str | None = Field(default=None, max_length=20)
    landmark: str | None = None
    postal_code: str | None = Field(default=None, max_length=20)
    country_code: str = Field(default="EG", min_length=2, max_length=2)


class order_create_request(BaseModel):
    cart_token: str = Field(min_length=1, max_length=64)
    customer: order_customer_input
    shipping_address: order_address_input
    payment_method: PaymentMethod
    # Which gateway will be used, when the method is card. The payment itself is
    # initiated in S4; S1 only records the intent.
    payment_provider: str | None = Field(default=None, max_length=64)


# --- Response ------------------------------------------------------------
class order_item_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_number: int
    # Section 2: the same string GA4/Ads send as item_id and Merchant as offer_id.
    sku: str
    item_group_id: str | None = None
    product_title: str
    variant_label: str | None = None
    variant_attributes: dict = {}
    brand: str | None = None
    category_path: str | None = None
    product_url: str | None = None
    item_list_id: str | None = None
    item_list_name: str | None = None

    unit_list_price: Decimal | None = None
    unit_price: Decimal
    quantity: int
    discount_amount: Decimal
    line_subtotal: Decimal
    tax_amount: Decimal
    line_total: Decimal

    # Section 11A historical snapshot. Null cogs with source 'unknown' is a
    # deliberate signal: the margin is unknown, not zero.
    unit_cogs: Decimal | None = None
    line_cogs: Decimal | None = None
    cogs_snapshot_source: str | None = None
    # Section 4.4 attribution: which offer priced this line, and by which
    # mechanism. A markdown and a campaign discount are not the same number.
    promotion_id: int | None = None
    discount_source: str | None = None


class order_address_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    address_type: str
    recipient_name: str
    phone: str
    phone_alt: str | None = None
    governorate: str
    city: str
    district: str | None = None
    street_address: str
    building: str | None = None
    floor: str | None = None
    apartment: str | None = None
    landmark: str | None = None
    postal_code: str | None = None
    country_code: str


class order_attribution_response(BaseModel):
    """The copied snapshot, not a live join."""

    model_config = ConfigDict(from_attributes=True)

    first_touch_at: datetime | None = None
    first_touch_source: str | None = None
    first_touch_medium: str | None = None
    first_touch_campaign: str | None = None
    first_touch_channel_group: str | None = None
    first_touch_landing_page: str | None = None

    last_touch_at: datetime | None = None
    last_touch_source: str | None = None
    last_touch_medium: str | None = None
    last_touch_campaign: str | None = None
    last_touch_channel_group: str | None = None
    last_touch_landing_page: str | None = None

    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    utm_id: str | None = None

    gclid: str | None = None
    gbraid: str | None = None
    wbraid: str | None = None
    fbclid: str | None = None
    fbp: str | None = None
    fbc: str | None = None

    ga_client_id: str | None = None
    ga_session_id: str | None = None
    affiliate_id: str | None = None
    referral_code: str | None = None
    coupon_code: str | None = None

    landing_page: str | None = None
    referrer: str | None = None
    locale: str | None = None
    visitor_token: str | None = None
    extras: dict = {}


class order_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Section 2: order_id AND the GA4/Ads transaction_id. Never regenerated.
    order_number: str
    status: str
    locale: str
    currency: str

    customer_public_id: str | None = None
    # Section 6: derived from order history, never from a client flag.
    is_new_customer: bool | None = None

    subtotal: Decimal
    discount: Decimal
    tax_total: Decimal
    shipping: Decimal
    total: Decimal
    gross_order_value: Decimal
    items_cogs_total: Decimal
    # Only the promotion half of the saving. Markdowns stay out of campaign
    # cost, per section 4.4.
    promotion_cost_total: Decimal = Decimal("0.00")
    coupon_code: str | None = None

    payment_status: str
    payment_method: str | None = None
    payment_provider: str | None = None
    cod_amount: Decimal | None = None
    cod_collection_status: str | None = None

    placed_at: datetime
    business_date: date | None = None

    items: list[order_item_response] = []
    shipping_address: order_address_response | None = None
    attribution: order_attribution_response | None = None
