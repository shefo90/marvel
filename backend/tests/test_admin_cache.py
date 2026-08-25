"""Admin writes must invalidate the cache, and must do it *after* the commit.

Two defects, both silent, both found here:

1. The first cache invalidation in this project was a no-op: INCR on a missing
   key returns 1, and the default version was already 1. Nothing failed. These
   tests assert the version *moved*.

2. The invalidation then ran inside the write transaction, before the route's
   ``db.commit()``. A storefront read landing in that window sees the
   pre-commit row, caches it, and that stale copy outlives the commit by up to
   ``TTL_PRICING`` (60s) -- a shopper served the old price after the operator
   was told the change had saved. These tests assert the cache is untouched
   until the transaction actually commits.

The suite runs on the rolled-back ``db`` fixture, so nothing here commits real
fixture rows: the wiring tests commit a session that wrote nothing, and the
write-path tests drain the pending work explicitly with ``run_pending``.
"""

import pytest
from sqlalchemy import text

from services import cache
from services.cache_invalidation import on_commit, run_pending


def _published_product(db, slug: str, ar_slug: str):
    """A product translated into both locales.

    Both, deliberately: ``_invalidate`` builds its key map from the translation
    rows, and a locale with no row can hold no cache entry -- ``get_product_by_slug``
    resolves a slug through ``ProductTranslation``, so it never caches under a
    locale the product has not been translated into. A single-locale fixture
    would let a one-locale invalidation look complete.
    """
    from repositories.admin_catalog import create_product, upsert_translation
    from tests.test_admin_writes import _actor, _level2_category, _locale

    _locale(db, "ar")
    _locale(db, "en")
    cat, actor = _level2_category(db), _actor(db)
    product = create_product(db, actor, {
        "title": "Cache", "slug": slug, "brand": "Pixi", "category_id": cat.id,
    })
    upsert_translation(db, actor, product.id, "en", {
        "title": "Sandal", "slug": slug, "description": "A sandal",
        "meta_description": "short",
    })
    upsert_translation(db, actor, product.id, "ar", {
        "title": "صندل", "slug": ar_slug, "description": "وصف",
        "meta_description": "قصير",
    })
    run_pending(db)  # discard the work the fixture writes queued
    return product, actor


# --- the deferral itself -------------------------------------------------

def test_deferred_work_runs_when_the_transaction_commits(db):
    ran = []
    on_commit(db, lambda: ran.append("ran"))

    assert ran == [], "work ran before the commit"
    db.commit()

    assert ran == ["ran"]


def test_deferred_work_is_discarded_when_the_transaction_rolls_back(db):
    ran = []
    db.execute(text("select 1"))  # open a transaction, so the rollback is real
    on_commit(db, lambda: ran.append("ran"))

    db.rollback()

    assert ran == [], "cache work ran for a transaction that never committed"


def test_one_failing_callback_does_not_break_the_commit_or_the_rest(db):
    """A Redis hiccup must not turn a successful write into a 500 -- the route
    has already committed by the time these run, so raising here would report
    failure for work that succeeded."""
    ran = []

    def boom():
        raise RuntimeError("redis went away")

    on_commit(db, boom)
    on_commit(db, lambda: ran.append("ran"))

    db.commit()

    assert ran == ["ran"]


# --- the admin write paths ----------------------------------------------

def test_an_admin_write_leaves_the_cache_alone_until_it_commits(db):
    """The live bug: a storefront read landing between the invalidation and the
    commit re-caches the pre-commit row for the whole of TTL_PRICING."""
    from repositories.admin_catalog import update_product

    product, actor = _published_product(db, "cache-defer-1", "كاش-ديفر-1")
    live = cache.key(cache.NS_PRODUCT, "ar", "كاش-ديفر-1")
    cache.set(live, {"price": "old"})

    update_product(db, actor, product.id, {"brand": "Renamed"})

    assert cache.get(live) == {"price": "old"}, (
        "the write dropped the cache before committing -- a concurrent read "
        "would refill it from the pre-commit row"
    )

    run_pending(db)
    assert cache.get(live) is None


def test_the_deferred_drop_clears_every_locale_the_product_has(db):
    from repositories.admin_catalog import update_product

    product, actor = _published_product(db, "cache-defer-2", "كاش-ديفر-2")
    keys = [
        cache.key(cache.NS_PRODUCT, "en", "cache-defer-2"),
        cache.key(cache.NS_PRODUCT, "ar", "كاش-ديفر-2"),
        cache.key(cache.NS_PRODUCT, "en", "id", product.id),
        cache.key(cache.NS_PRODUCT, "ar", "id", product.id),
    ]
    for k in keys:
        cache.set(k, {"stale": True})

    update_product(db, actor, product.id, {"brand": "Renamed"})
    run_pending(db)

    assert [cache.get(k) for k in keys] == [None, None, None, None]


def test_renaming_a_slug_drops_the_old_slugs_key_on_commit(db):
    """A renamed locale's OLD slug is what ``get_product_by_slug`` is keyed on,
    and no current row carries it, so it has to be passed through explicitly."""
    from repositories.admin_catalog import upsert_translation

    product, actor = _published_product(db, "cache-defer-3", "كاش-ديفر-3")
    old_key = cache.key(cache.NS_PRODUCT, "ar", "كاش-ديفر-3")
    cache.set(old_key, {"stale": True})

    upsert_translation(db, actor, product.id, "ar", {"slug": "كاش-ديفر-3-جديد"})

    assert cache.get(old_key) == {"stale": True}, "dropped before the commit"
    run_pending(db)
    assert cache.get(old_key) is None


def test_publishing_bumps_the_listing_version_on_commit(db):
    from repositories.admin_catalog import generate_variants, publish_product

    product, actor = _published_product(db, "cache-probe", "كاش-بروب")
    generate_variants(db, actor, product.id, ["38"], ["black"], {"price": "500.00"})
    run_pending(db)

    before = cache.namespace_version(cache.NS_LISTING)
    publish_product(db, actor, product.id, "ar")
    assert cache.namespace_version(cache.NS_LISTING) == before, (
        "listing version moved before the publish committed"
    )

    run_pending(db)
    assert cache.namespace_version(cache.NS_LISTING) != before, (
        "listing cache version did not move — invalidation is a no-op"
    )
