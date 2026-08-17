"""Environment-derived settings.

Infrastructure wiring only — imports nothing from the application layers.
Section 13: no hardcoded hosts, ports or secrets; everything from the environment.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Commerce constants. The store is single-market and single-currency by design
# (see spec section 2 "Decisions locked"): Egypt, EGP, no market-scoped pricing.
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "EGP")
DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "en")
HOUSE_BRAND = os.getenv("HOUSE_BRAND", "Pixi")

# Section 2: the order number is the immutable commerce identity and doubles as
# the GA4/Google Ads transaction_id. It is generated once and never regenerated.
ORDER_NUMBER_PREFIX = os.getenv("ORDER_NUMBER_PREFIX", "ORD")

# Open question 5 — the retention window must be confirmed against the payment
# gateway's retry horizon. A window shorter than that horizon would let a very
# late gateway retry bypass replay protection.
IDEMPOTENCY_TTL_HOURS = int(os.getenv("IDEMPOTENCY_TTL_HOURS", "24"))

# Open question 6 — cart lifecycle values are a business decision the spec does
# not set. These are the documented defaults.
GUEST_CART_TTL_DAYS = int(os.getenv("GUEST_CART_TTL_DAYS", "30"))
CUSTOMER_CART_TTL_DAYS = int(os.getenv("CUSTOMER_CART_TTL_DAYS", "90"))
CART_ABANDONED_AFTER_HOURS = int(os.getenv("CART_ABANDONED_AFTER_HOURS", "24"))

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
