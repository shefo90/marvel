"""Sitemaps and robots.txt.

Membership is not a judgement made here. ``ix_product_translations_sitemap`` is
a partial index whose predicate *is* the rule:

    is_published AND robots_index AND is_complete AND canonical_override IS NULL

so this query repeats that predicate exactly and the index serves it. Anything
else would be a second definition of "indexable", and the two would drift.

A sitemap listing a page we told Google not to index is worse than no sitemap —
it is a direct request to crawl something we asked it to ignore.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import SITE_BASE_URL
from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collection_translations import CollectionTranslation
from models.collections import Collection
from models.locales import Locale
from models.product_translations import ProductTranslation
from models.products import Product

XML_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"


def product_url(locale: str, slug: str) -> str:
    """The canonical address of one product in one language.

    The single place the storefront's product path is built. ``admin_slugs``
    has its own copy for redirect rows and the two must agree; S2 changing this
    segment has to change both.
    """
    return f"{SITE_BASE_URL}/{locale}/products/{slug}"


def category_url(locale: str, slug: str) -> str:
    """``/c/`` so an operator-chosen category slug can never shadow a product."""
    return f"{SITE_BASE_URL}/{locale}/c/{slug}"


def collection_url(locale: str, slug: str) -> str:
    return f"{SITE_BASE_URL}/{locale}/edit/{slug}"


def _indexable():
    """The partial index's predicate, as a query filter."""
    return (
        ProductTranslation.is_published.is_(True),
        ProductTranslation.robots_index.is_(True),
        ProductTranslation.is_complete.is_(True),
        ProductTranslation.canonical_override.is_(None),
        # The one condition the index cannot express: an archived product is a
        # 404 whatever its translations say.
        Product.status == "active",
    )


def sitemap_entries(db: Session, locale: str) -> list[dict]:
    """Every indexable product URL in one language, with its hreflang cluster.

    Two queries regardless of catalogue size: the pages, then the sibling
    translations that form the clusters.
    """
    rows = list(
        db.execute(
            select(ProductTranslation)
            .join(Product, Product.id == ProductTranslation.product_id)
            .where(ProductTranslation.locale == locale, *_indexable())
            .order_by(ProductTranslation.content_updated_at.desc())
        ).scalars()
    )
    if not rows:
        return []

    siblings: dict[int, dict[str, str]] = {}
    for translation in db.execute(
        select(ProductTranslation)
        .join(Product, Product.id == ProductTranslation.product_id)
        .where(
            ProductTranslation.product_id.in_([row.product_id for row in rows]),
            *_indexable(),
        )
    ).scalars():
        siblings.setdefault(translation.product_id, {})[translation.locale] = product_url(
            translation.locale, translation.slug
        )

    entries = []
    for row in rows:
        cluster = siblings.get(row.product_id, {})
        entries.append({
            "loc": product_url(row.locale, row.slug),
            "lastmod": row.content_updated_at,
            # A cluster of one emits no hreflang at all: a self-referential
            # cluster is noise rather than a signal, and a sibling that is not
            # indexable is a 404 we would be pointing Google at.
            "alternates": cluster if len(cluster) > 1 else {},
        })
    return entries


def _taxonomy_entries(
    db: Session, locale: str, *, owner, translation, owner_id, url_for
) -> list[dict]:
    """Indexable category or collection URLs, with their hreflang clusters.

    Same shape as ``sitemap_entries`` and the same rule, applied to a different
    pair of tables. Written once and parameterised rather than copied, because
    the interesting part is the predicate and two copies of it would drift.

    Note that this is a *stricter* test than the one the navigation menu uses.
    ``repositories.taxonomy`` shows a category in the menu on a published
    translation alone, because a menu entry needs no meta description. Appearing
    in a sitemap is a request to index, so it additionally requires
    ``is_complete`` -- asking Google to crawl a page with no description is
    asking it to index a thin one.
    """
    def indexable():
        return (
            translation.is_published.is_(True),
            translation.robots_index.is_(True),
            translation.is_complete.is_(True),
            translation.canonical_override.is_(None),
            owner.is_active.is_(True),
            owner.is_indexable.is_(True),
        )

    rows = list(
        db.execute(
            select(translation)
            .join(owner, owner.id == owner_id)
            .where(translation.locale == locale, *indexable())
            .order_by(translation.content_updated_at.desc())
        ).scalars()
    )
    if not rows:
        return []

    ids = [getattr(row, owner_id.name) for row in rows]
    siblings: dict[int, dict[str, str]] = {}
    for row in db.execute(
        select(translation)
        .join(owner, owner.id == owner_id)
        .where(owner_id.in_(ids), *indexable())
    ).scalars():
        siblings.setdefault(getattr(row, owner_id.name), {})[row.locale] = url_for(
            row.locale, row.slug
        )

    entries = []
    for row in rows:
        cluster = siblings.get(getattr(row, owner_id.name), {})
        entries.append({
            "loc": url_for(row.locale, row.slug),
            "lastmod": row.content_updated_at,
            "alternates": cluster if len(cluster) > 1 else {},
        })
    return entries


def category_entries(db: Session, locale: str) -> list[dict]:
    return _taxonomy_entries(
        db, locale, owner=Category, translation=CategoryTranslation,
        owner_id=CategoryTranslation.__table__.c.category_id,
        url_for=category_url,
    )


def collection_entries(db: Session, locale: str) -> list[dict]:
    return _taxonomy_entries(
        db, locale, owner=Collection, translation=CollectionTranslation,
        owner_id=CollectionTranslation.__table__.c.collection_id,
        url_for=collection_url,
    )


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def sitemap_for_locale(db: Session, locale: str) -> str:
    """One language's sitemap, with reciprocal hreflang on every URL."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset xmlns="{XML_NS}" xmlns:xhtml="{XHTML_NS}">',
    ]
    # Categories and collections first: they are the shop's stable, hand-curated
    # pages, and a crawler that reads only part of a large sitemap should meet
    # those before the long tail of individual products.
    entries = (
        category_entries(db, locale)
        + collection_entries(db, locale)
        + sitemap_entries(db, locale)
    )
    for entry in entries:
        parts.append("  <url>")
        parts.append(f"    <loc>{_escape(entry['loc'])}</loc>")
        parts.append(f"    <lastmod>{entry['lastmod'].date().isoformat()}</lastmod>")
        for alternate_locale, url in sorted(entry["alternates"].items()):
            parts.append(
                f'    <xhtml:link rel="alternate" hreflang="{alternate_locale}" '
                f'href="{_escape(url)}"/>'
            )
        parts.append("  </url>")
    parts.append("</urlset>")
    return "\n".join(parts)


def sitemap_index(db: Session) -> str:
    """One entry per active language.

    Split by locale rather than one flat file because the two languages are
    published independently — an Arabic-only content push should not invalidate
    the English sitemap's freshness signal.
    """
    locales = list(
        db.execute(
            select(Locale.code)
            .where(Locale.is_active.is_(True))
            .order_by(Locale.sort_order, Locale.code)
        ).scalars()
    )
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<sitemapindex xmlns="{XML_NS}">']
    for code in locales:
        parts.append("  <sitemap>")
        parts.append(f"    <loc>{SITE_BASE_URL}/sitemap-{code}.xml</loc>")
        parts.append("  </sitemap>")
    parts.append("</sitemapindex>")
    return "\n".join(parts)


def robots_txt() -> str:
    """What crawlers may not have.

    ``/admin`` is excluded here and from the sitemap, per section 2.1. The cart
    and checkout are per-shopper pages with nothing to index; listing them only
    burns crawl budget on URLs that differ for every visitor.
    """
    return "\n".join([
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /cart",
        "Disallow: /checkout",
        "Disallow: /api/",
        "",
        f"Sitemap: {SITE_BASE_URL}/sitemap.xml",
        "",
    ])
