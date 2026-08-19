"""Back-office order contracts. No logic here — see repositories/admin_orders.py."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from core.enums import OrderStatus


class admin_order_row(BaseModel):
    order_number: str
    status: str
    payment_status: str
    payment_method: str
    cod_collection_status: str | None = None
    total: Decimal
    currency: str
    locale: str
    customer_email: str | None = None
    placed_at: datetime | None = None


class admin_order_list_response(BaseModel):
    items: list[admin_order_row]
    page: int
    page_size: int
    total: int


class admin_order_item(BaseModel):
    line_number: int
    sku: str
    product_title: str
    variant_label: str | None = None
    quantity: int
    unit_list_price: Decimal | None = None
    unit_price: Decimal
    discount_amount: Decimal
    # Which mechanism produced the discount. A markdown is not a campaign cost.
    discount_source: str | None = None
    line_total: Decimal
    refunded_quantity: int


class admin_order_history_entry(BaseModel):
    dimension: str
    from_status: str | None = None
    to_status: str
    actor_type: str
    actor_user_id: int | None = None
    reason: str | None = None
    created_at: datetime


class admin_order_detail(BaseModel):
    order_id: int
    order_number: str
    status: str
    payment_status: str
    payment_method: str
    cod_collection_status: str | None = None
    locale: str
    currency: str
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax_total: Decimal
    total: Decimal
    promotion_cost_total: Decimal
    refunded_amount_total: Decimal
    customer_email: str | None = None
    customer_phone: str | None = None
    placed_at: datetime | None = None
    items: list[admin_order_item] = []
    status_history: list[admin_order_history_entry] = []


class admin_order_status_update(BaseModel):
    # Typed against the enum, so an unknown status is a 422 at the boundary
    # rather than a row the lifecycle has no meaning for.
    status: OrderStatus
    reason: str | None = Field(default=None, max_length=500)
