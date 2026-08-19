"""Shared enumerations.

Every enum is persisted as a VARCHAR + CHECK constraint (``native_enum=False``)
rather than a PostgreSQL native ENUM type, so adding a value is an ordinary
Alembic migration instead of an ``ALTER TYPE``. Spec open question 2 anticipates
exactly this for the card authorize/capture split.
"""

from enum import Enum


class OrderStatus(str, Enum):
    """Commerce lifecycle of the order itself, independent of payment."""

    pending = "pending"
    confirmed = "confirmed"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


class PaymentStatus(str, Enum):
    """Section 9 state/event table.

    Deliberately omits ``authorized``/``captured``: section 9 lists only
    initiated / succeeded / failed. If the selected Egyptian gateway separates
    authorization from capture, add the values via migration rather than
    overloading ``initiated`` (spec open question 2).
    """

    pending = "pending"
    initiated = "initiated"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"


class PaymentMethod(str, Enum):
    cod = "cod"
    card = "card"


class CodCollectionStatus(str, Enum):
    """COD money movement, section 3 and section 10."""

    pending = "pending"
    collected = "collected"
    remitted = "remitted"
    failed = "failed"


class ShipmentStatus(str, Enum):
    """Section 10's normalized internal status set, verbatim.

    Provider-specific strings are mapped onto these by the courier adapter in
    S4; business code never sees a raw provider status.
    """

    shipment_created = "shipment_created"
    ready_for_pickup = "ready_for_pickup"
    picked_up = "picked_up"
    in_transit = "in_transit"
    out_for_delivery = "out_for_delivery"
    delivered = "delivered"
    delivery_failed = "delivery_failed"
    postponed = "postponed"
    return_initiated = "return_initiated"
    returned = "returned"
    return_received = "return_received"
    cancelled = "cancelled"
    cod_collected = "cod_collected"
    cod_remitted = "cod_remitted"


class RefundStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class CartStatus(str, Enum):
    active = "active"
    abandoned = "abandoned"
    converted = "converted"
    expired = "expired"


class JobStatus(str, Enum):
    """There is deliberately no ``done``.

    A job that succeeds is deleted, so the table only ever holds work that is
    outstanding, in flight, or dead. That keeps it small without a retention
    policy, and makes the dead-letter queue a plain SELECT rather than a view
    over history nobody prunes.
    """

    pending = "pending"
    running = "running"
    dead = "dead"


class TranslationStatus(str, Enum):
    """Section 6.2 of the design: only ``published`` rows are hreflang cluster
    members. Draft and machine-stub rows are never members, and never enter a
    sitemap."""

    draft = "draft"
    machine_stub = "machine_stub"
    published = "published"


class TextDirection(str, Enum):
    ltr = "ltr"
    rtl = "rtl"


class AuditAction(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class PromotionType(str, Enum):
    """Section 4 of the admin design. No stacking, no priority, no tiers.

    ``bogo`` is the only one that reasons across a whole line rather than a
    single unit, which is why pricing evaluates it separately.
    """

    percentage = "percentage"
    fixed = "fixed"
    bogo = "bogo"


class PromotionTargetType(str, Enum):
    """What a promotion applies to. ``all`` must be chosen explicitly -- a
    promotion with no targets applies to nothing, so a half-saved offer cannot
    mark the whole catalogue down."""

    all = "all"
    product = "product"
    variant = "variant"
    category = "category"
    collection = "collection"


class DiscountSource(str, Enum):
    """Which mechanism produced a line's discount.

    The distinction is a reporting one and it matters: a markdown is not a
    campaign cost. ``orders.promotion_cost_total`` sums only the ``promotion``
    rows, while a ``sale_price`` markdown stays visible as
    unit_list_price - unit_price without being counted as spend.
    """

    sale_price = "sale_price"
    promotion = "promotion"


class ProductStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class StaffRole(str, Enum):
    """Staff roles. Ordered by privilege in services/role_access_level.py."""

    admin = "admin"
    operations = "operations"
    catalog = "catalog"
    support = "support"


class CustomerStatus(str, Enum):
    active = "active"
    merged = "merged"
    anonymized = "anonymized"


class IdentityType(str, Enum):
    email = "email"
    phone = "phone"


class IdentitySource(str, Enum):
    order = "order"
    account = "account"
    admin = "admin"
    merge = "merge"


class MergeRule(str, Enum):
    exact_email = "exact_email"
    exact_phone = "exact_phone"
    email_and_phone = "email_and_phone"
    account_login = "account_login"
    manual_admin = "manual_admin"


class ActorType(str, Enum):
    system = "system"
    staff = "staff"
    customer = "customer"


class AddressType(str, Enum):
    shipping = "shipping"
    billing = "billing"


class ProductCondition(str, Enum):
    new = "new"
    refurbished = "refurbished"
    used = "used"


class Gender(str, Enum):
    male = "male"
    female = "female"
    unisex = "unisex"


class AgeGroup(str, Enum):
    newborn = "newborn"
    infant = "infant"
    toddler = "toddler"
    kids = "kids"
    adult = "adult"


class AttributeType(str, Enum):
    size = "size"
    color = "color"
    material = "material"


class Availability(str, Enum):
    """Merchant-compatible availability values (section 8)."""

    in_stock = "in_stock"
    out_of_stock = "out_of_stock"
    preorder = "preorder"
    backorder = "backorder"
