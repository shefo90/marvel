"""Redis cache helper.

Stateless: no DB session, no domain knowledge, no model imports — it moves JSON
in and out of Redis and builds keys. Repositories decide *what* to cache.

Three rules this module exists to enforce:

1. **Every key is locale-scoped.** Catalog content differs per locale, so a key
   without a locale segment will serve Arabic content to English visitors the
   first time the caches cross. There is no API here that lets you omit it.

2. **Price and stock get a short TTL, content gets a long one.** Section 8
   requires that "Price, currency and availability must match what the shopper
   sees", and section 8 lists "price mismatch" and "availability mismatch" as
   Merchant diagnostics to monitor. A stale cached price *is* that defect. So
   descriptive content (titles, descriptions, images, SEO fields) caches for
   hours; anything carrying money or stock caches for a minute at most, and is
   invalidated explicitly on write.

3. **A Redis outage degrades to a cache miss, never to a 500.** Every operation
   swallows connection errors and reports a miss, so the storefront keeps
   serving from Postgres if Redis disappears.

**Invalidation** is namespace-versioned. Bumping the namespace version makes
every key under it unreachable in one O(1) write, instead of scanning for keys
to delete — ``SCAN``-and-delete over a large keyspace is exactly the kind of
operation that stalls a production Redis.

Never cache: carts, orders, customers, or anything keyed to a single shopper.
Those are mutable per-request state, and a shared cache is how one shopper ends
up seeing another's basket.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from redis.exceptions import RedisError

from core.db import redis_client

log = logging.getLogger(__name__)

# --- TTL policy ----------------------------------------------------------
# Descriptive catalog content: changes only when an admin edits it, and every
# edit invalidates explicitly, so this can be generous.
TTL_CONTENT = 60 * 60 * 6
# Listings: cheap to rebuild, and staleness shows up as ordering drift.
TTL_LISTING = 60 * 10
# Anything carrying price or stock. Deliberately short — see rule 2 above.
TTL_PRICING = 60
# Slug -> entity resolution and redirect lookups.
TTL_ROUTING = 60 * 30

_PREFIX = "marvel"


def _version_key(namespace: str) -> str:
    return f"{_PREFIX}:ver:{namespace}"


def namespace_version(namespace: str) -> int:
    """Current version of a cache namespace. Missing or unreachable -> 0.

    The default MUST be 0, not 1. ``invalidate_namespace`` uses ``INCR``, and
    Redis sets a missing key to 1 on the first increment — so with a default of
    1 the first invalidation moved the version from 1 to 1 and changed nothing.
    Every cached entry survived the first catalog edit, which is precisely the
    stale-price defect section 8 tells us to monitor for.
    """
    try:
        raw = redis_client.get(_version_key(namespace))
        return int(raw) if raw else 0
    except (RedisError, ValueError, TypeError):
        # Unreachable Redis: any stable value works, because nothing can be
        # read from the cache anyway.
        return 0


def invalidate_namespace(namespace: str) -> None:
    """Make every key in a namespace unreachable, in one write.

    Call after any catalog mutation broad enough that per-entity invalidation
    would be guesswork — a category rename, a bulk price import, a translation
    publish that changes hreflang cluster membership.
    """
    try:
        redis_client.incr(_version_key(namespace))
    except RedisError as exc:
        log.warning("cache: namespace invalidation failed for %s: %s", namespace, exc)


def key(namespace: str, locale: str, *parts: Any) -> str:
    """Build a versioned, locale-scoped cache key.

    ``marvel:v3:product:en:sandal-leather-black``
    """
    if not locale:
        raise ValueError("cache keys must be locale-scoped")
    tail = ":".join(str(p) for p in parts)
    return f"{_PREFIX}:v{namespace_version(namespace)}:{namespace}:{locale}:{tail}"


def get(cache_key: str) -> Any | None:
    try:
        raw = redis_client.get(cache_key)
    except RedisError as exc:
        log.warning("cache: get failed for %s: %s", cache_key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # A poisoned value must never take the request down.
        log.warning("cache: undecodable value at %s", cache_key)
        return None


def set(cache_key: str, value: Any, ttl: int = TTL_CONTENT) -> None:
    try:
        redis_client.setex(cache_key, ttl, json.dumps(value, default=str))
    except RedisError as exc:
        log.warning("cache: set failed for %s: %s", cache_key, exc)


def delete(*cache_keys: str) -> None:
    if not cache_keys:
        return
    try:
        redis_client.delete(*cache_keys)
    except RedisError as exc:
        log.warning("cache: delete failed: %s", exc)


def get_or_set(cache_key: str, producer: Callable[[], Any], ttl: int = TTL_CONTENT) -> Any:
    """Read through the cache, computing and storing on a miss.

    Deliberately not locked. A thundering herd on a catalog read costs a few
    duplicate Postgres queries; a distributed lock costs a new failure mode, and
    this workload does not justify it.
    """
    hit = get(cache_key)
    if hit is not None:
        return hit
    value = producer()
    if value is not None:
        set(cache_key, value, ttl)
    return value


# --- Namespaces ----------------------------------------------------------
NS_PRODUCT = "product"
NS_CATEGORY = "category"
NS_COLLECTION = "collection"
NS_LISTING = "listing"
NS_ROUTING = "routing"


def invalidate_product(product_id: int, slugs_by_locale: dict[str, str]) -> None:
    """Targeted invalidation after a single product changes.

    ``slugs_by_locale`` must include *every* locale the product is published in;
    a missing locale leaves that locale serving the old content. Callers get it
    from the product's translation rows rather than assuming.
    """
    keys = [key(NS_PRODUCT, loc, slug) for loc, slug in slugs_by_locale.items()]
    keys += [key(NS_PRODUCT, loc, "id", product_id) for loc in slugs_by_locale]
    delete(*keys)
    # Listings embed product cards, so any product edit makes them stale.
    invalidate_namespace(NS_LISTING)


def ping() -> bool:
    """Whether Redis is actually reachable. For the health endpoint."""
    try:
        return bool(redis_client.ping())
    except RedisError:
        return False
