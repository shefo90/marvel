"""Re-export every model so SQLAlchemy resolves string-based relationship
targets regardless of import order.

Alembic's ``env.py`` imports this module, so a table missing from this list is a
table missing from every migration.
"""

# --- Background work (no FKs: a job outlives the row that queued it) ------
from .jobs import Job

# --- Localization spine (imported first: translations FK to locales) -------
from .locales import Locale

# --- Identity / auth -------------------------------------------------------
from .users import User
from .refresh_token import RefreshToken
from .customers import Customer
from .customer_identity import CustomerIdentity
from .customer_credential import CustomerCredential
from .customer_refresh_token import CustomerRefreshToken
from .customer_merge import CustomerMerge

# --- Catalog ---------------------------------------------------------------
from .categories import Category
from .products import Product
from .product_variants import ProductVariant
from .collections import Collection
from .collection_products import CollectionProduct
from .product_images import ProductImage
from .promotions import Promotion
from .promotion_targets import PromotionTarget
from .attribute_values import AttributeValue

# --- Catalog translations --------------------------------------------------
from .product_translations import ProductTranslation
from .category_translations import CategoryTranslation
from .collection_translations import CollectionTranslation
from .product_image_translations import ProductImageTranslation
from .attribute_value_translations import AttributeValueTranslation
from .url_redirects import UrlRedirect

# --- Attribution -----------------------------------------------------------
from .attribution_visitors import AttributionVisitor
from .attribution_touches import AttributionTouch
from .cart_attributions import CartAttribution
from .customer_attributions import CustomerAttribution
from .order_attributions import OrderAttribution

# --- Cart ------------------------------------------------------------------
from .carts import Cart
from .cart_items import CartItem
from .cart_mutations import CartMutation

# --- Orders ----------------------------------------------------------------
from .orders import Order
from .order_items import OrderItem
from .order_status_history import OrderStatusHistory
from .order_audit_log import OrderAuditLog
from .idempotency_keys import IdempotencyKey

# --- Addresses -------------------------------------------------------------
from .addresses import Address
from .order_addresses import OrderAddress

# --- Payments --------------------------------------------------------------
from .payment_transactions import PaymentTransaction
from .order_payment_events import OrderPaymentEvent
from .refunds import Refund
from .refund_items import RefundItem

# --- Fulfilment (Tier 2: schema only in S1, wired in S4) -------------------
from .courier_providers import CourierProvider
from .courier_status_mappings import CourierStatusMapping
from .shipments import Shipment
from .shipment_status_events import ShipmentStatusEvent
from .order_returns import OrderReturn
from .order_return_items import OrderReturnItem

# --- Behaviour, not tables -------------------------------------------------
# Imported last: it registers a flush listener against the models above, so
# every one of them must already exist. Importing it for the side effect is the
# point -- nothing references the module by name.
from . import feed_timestamps  # noqa: F401

__all__ = [
    "Locale",
    "User",
    "RefreshToken",
    "Customer",
    "CustomerIdentity",
    "CustomerCredential",
    "CustomerRefreshToken",
    "CustomerMerge",
    "Category",
    "Product",
    "ProductVariant",
    "Collection",
    "CollectionProduct",
    "ProductImage",
    "Promotion",
    "PromotionTarget",
    "AttributeValue",
    "ProductTranslation",
    "CategoryTranslation",
    "CollectionTranslation",
    "ProductImageTranslation",
    "AttributeValueTranslation",
    "UrlRedirect",
    "AttributionVisitor",
    "AttributionTouch",
    "CartAttribution",
    "CustomerAttribution",
    "OrderAttribution",
    "Cart",
    "CartItem",
    "CartMutation",
    "Order",
    "OrderItem",
    "OrderStatusHistory",
    "OrderAuditLog",
    "IdempotencyKey",
    "Address",
    "OrderAddress",
    "PaymentTransaction",
    "OrderPaymentEvent",
    "Refund",
    "RefundItem",
    "CourierProvider",
    "CourierStatusMapping",
    "Shipment",
    "ShipmentStatusEvent",
    "OrderReturn",
    "OrderReturnItem",
    "Job",
]
