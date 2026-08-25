"""Admin writes must actually invalidate, not merely call the invalidator.

The first cache invalidation in this project was a no-op: INCR on a missing key
returns 1, and the default version was already 1. Nothing failed. These tests
assert the version *moved*.
"""

from services import cache


def test_publishing_bumps_the_listing_version(db, monkeypatch):
    from repositories.admin_catalog import (
        create_product, generate_variants, publish_product,
    )
    from tests.test_admin_writes import _actor, _level2_category, _locale

    _locale(db, "ar")
    cat, actor = _level2_category(db), _actor(db)
    product = create_product(db, actor, {
        "title": "Cache", "slug": "cache-probe", "brand": "Pixi",
        "category_id": cat.id,
    })
    generate_variants(db, actor, product.id, ["38"], ["black"], {"price": "500.00"})

    from repositories.admin_catalog import upsert_translation
    upsert_translation(db, actor, product.id, "ar", {
        "title": "صندل", "description": "وصف", "meta_description": "قصير",
    })

    before = cache.namespace_version(cache.NS_LISTING)
    publish_product(db, actor, product.id, "ar")
    after = cache.namespace_version(cache.NS_LISTING)

    assert after != before, "listing cache version did not move — invalidation is a no-op"
