"""Contracts for the signed-in shopper.

Zero logic — Pydantic models only.

Deliberately narrower than the admin's view of the same rows. An order carries
``items_cogs_total``, ``contribution_profit``, ``gateway_fee`` and the rest of
section 11A's margin columns; a shopper is shown what they paid and what is
happening to their parcel. Building the response from an explicit field list
rather than ``from_attributes`` over the whole model is what keeps a column
added for reporting next year from appearing on a customer-facing page.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class account_session_response(BaseModel):
    """Sign-in and refresh.

    No ``refresh_token`` field, and its absence is the design: the refresh token
    is set as an httpOnly cookie and must never be readable by the page. See
    ``services/session_cookies.py``.

    ``csrf_token`` is returned as well as set as a cookie, so a client can hold
    it in memory instead of reading the cookie back on every request. The value
    is the same either way; it is not a credential on its own.
    """

    access_token: str
    token_type: str = "bearer"
    csrf_token: str


class account_profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    orders_count: int = 0


class account_order_row(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_number: str
    status: str
    payment_status: str
    payment_method: str | None = None
    currency: str
    total: Decimal
    placed_at: datetime | None = None
    business_date: date | None = None
    item_count: int = 0


class account_order_item(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    product_title: str
    variant_label: str | None = None
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class account_order_detail(account_order_row):
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax_total: Decimal
    coupon_code: str | None = None
    items: list[account_order_item] = []


class account_address(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str | None = None
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
    is_default_shipping: bool = False


class account_address_create(BaseModel):
    label: str | None = Field(default=None, max_length=50)
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
    is_default_shipping: bool = False


class account_address_update(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    recipient_name: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=20)
    phone_alt: str | None = Field(default=None, max_length=20)
    governorate: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    street_address: str | None = None
    building: str | None = Field(default=None, max_length=50)
    floor: str | None = Field(default=None, max_length=20)
    apartment: str | None = Field(default=None, max_length=20)
    landmark: str | None = None
    postal_code: str | None = Field(default=None, max_length=20)
    is_default_shipping: bool | None = None
