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

# Background worker. The queue is a Postgres table, not Redis: a job row is
# written in the same transaction as the change that caused it, so the two can
# never disagree -- see repositories/jobs.py.
#
# JOB_LEASE_SECONDS is how long a claimed job may stay claimed before another
# worker assumes the first one died. It must exceed the slowest handler's
# runtime, or two workers will run the same job concurrently.
JOB_POLL_SECONDS = float(os.getenv("JOB_POLL_SECONDS", "2"))
JOB_BATCH_SIZE = int(os.getenv("JOB_BATCH_SIZE", "5"))
JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "300"))
JOB_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "5"))
JOB_RETRY_BASE_SECONDS = float(os.getenv("JOB_RETRY_BASE_SECONDS", "10"))
JOB_RETRY_CAP_SECONDS = float(os.getenv("JOB_RETRY_CAP_SECONDS", "900"))

# Uploaded imagery. The one piece of state that is not in Postgres, which means
# a Postgres backup does not cover it -- the volume behind MEDIA_ROOT must be in
# the backup procedure. MEDIA_URL_PREFIX is what the browser sees, so moving the
# files to a CDN later is a prefix change rather than a data migration.
MEDIA_ROOT = os.getenv("MEDIA_ROOT", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media"))
MEDIA_URL_PREFIX = os.getenv("MEDIA_URL_PREFIX", "/media")

# The storefront's public origin. Sitemaps must carry absolute URLs, and a
# canonical tag is only meaningful as an absolute one -- so this is required
# infrastructure, not a nicety. Section 13: from the environment, never hardcoded.
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:3000").rstrip("/")

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
