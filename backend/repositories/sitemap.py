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
    for entry in sitemap_entries(db, locale):
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
