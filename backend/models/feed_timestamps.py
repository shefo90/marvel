"""Keeps the three "what changed?" timestamps honest, on every write path.

S6's catalog sync is incremental: it asks the database which variants have moved
since the last run rather than pushing 23 products every time. That question is
answered by ``catalog_updated_at``, ``inventory_updated_at`` and
``content_updated_at`` -- and until this module existed, *nothing wrote them*.
Every edit an operator made was invisible to the feed.

**Why a mapper event and not an assignment in each repository.** The obvious fix
is a line in ``update_variant``. That is also how it came to be broken: the
column has existed since ``0001``, and every write path since -- the admin
repositories, the seed scripts, ``import_local_images`` -- was written without
one. A rule that must be remembered at every call site eventually is not. Here
it is remembered once, and a write path added next year inherits it without
knowing this module exists.

**Deny-list, not allow-list.** A field is a catalog field unless it is named
below as something else. The inverse -- listing the fields that count -- fails
silently in exactly the direction that hurt: add a column to the feed payload,
forget to add it here, and the feed quietly stops noticing edits to it. With a
deny-list a new column is over-reported at worst, which costs one redundant
push instead of an invisible staleness bug.

**Three exclusions earn their place:**

- ``cost`` is COGS. It appears in no feed anywhere. Bumping a feed timestamp for
  it would push Merchant Center a payload whose every visible field is
  byte-identical to the one it already has.
- ``availability`` and ``stock_quantity`` are inventory, not catalog. Merchant
  treats a catalog change as grounds for re-review; a shop that sells its last
  pair of 38s should not thereby re-open review on the offer.
- Bookkeeping columns (the timestamps themselves, ``created_at``/``updated_at``)
  cannot count, or parking a timestamp deliberately -- as the tests and any
  future backfill must -- would immediately un-park it.

The clock is the database's ``now()``, never Python's, matching the discipline
``models/jobs.py`` sets out. Note that in Postgres ``now()`` is the *transaction*
timestamp: every row touched by one transaction gets one identical value, and it
does not advance mid-transaction. That is the desired behaviour -- an operator's
single save is one moment for the feed, not five -- but it does mean a test
cannot create and edit a row in one transaction and expect the two timestamps to
differ.
"""

from __future__ import annotations

from sqlalchemy import event, func, inspect
from sqlalchemy.orm import Session

from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collection_translations import CollectionTranslation
from models.collections import Collection
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product

# Never evidence of a change; see the module docstring.
_BOOKKEEPING = frozenset({
    "created_at",
    "updated_at",
    "catalog_updated_at",
    "inventory_updated_at",
    "content_updated_at",
})

_INVENTORY_FIELDS = frozenset({"availability", "stock_quantity"})

# Identity and COGS. Neither reaches a feed.
_NOT_CATALOG = _BOOKKEEPING | _INVENTORY_FIELDS | frozenset({"id", "product_id", "cost"})

# Rows whose content is what a sitemap's ``lastmod`` is reporting.
_CONTENT_MODELS = (
    Product,
    ProductTranslation,
    Category,
    CategoryTranslation,
    Collection,
    CollectionTranslation,
)


def _changed_fields(obj) -> set[str]:
    """The column attributes this object has actually been assigned new values for.

    ``session.dirty`` is a superset -- it holds anything that *might* have
    changed, including an object assigned a value equal to the one it already
    had. Consulting the attribute history instead means a no-op save does not
    announce itself to the feed as an edit.
    """
    state = inspect(obj)
    return {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }


@event.listens_for(Session, "before_flush")
def _stamp_feed_timestamps(session: Session, flush_context, instances) -> None:
    for obj in session.dirty:
        if not isinstance(obj, (ProductVariant,) + _CONTENT_MODELS):
            continue

        changed = _changed_fields(obj)
        if not changed:
            continue

        if isinstance(obj, ProductVariant):
            if changed & _INVENTORY_FIELDS:
                obj.inventory_updated_at = func.now()
            if changed - _NOT_CATALOG:
                obj.catalog_updated_at = func.now()
        elif changed - _BOOKKEEPING:
            obj.content_updated_at = func.now()
