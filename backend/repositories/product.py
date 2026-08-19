"""Catalog reads.

Owns all querying and the cache policy. Routes never touch SQLAlchemy.

**Cache policy.** Product detail is cached as a fully-serialized dict keyed by
``(namespace_version, locale, slug)``. Two consequences worth stating:

* Price and stock live inside that cached payload, so it uses ``TTL_PRICING``
  (60s), not ``TTL_CONTENT``. Section 8 requires the page price to match the
  Merchant feed, and section 8 lists "price mismatch" and "availability
  mismatch" as diagnostics to monitor — a long-lived cached price *is* that
  defect. Admin writes must additionally call ``cache.invalidate_product``.
* The locale is part of the key by construction (``services.cache.key`` refuses
  a blank locale), so Arabic content can never be served to an English request.

**Fallback policy.** A product with no published translation in the requested
locale is *not* silently served in the other language — it 404s for that locale.
Serving English under ``/ar/`` would create a near-duplicate page and, worse,
would make the hreflang cluster claim an Arabic version that does not exist.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collections import Collection
from models.collection_products import CollectionProduct
from models.product_images import ProductImage
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product
from services import cache


def _published(stmt, locale: str):
    """Only complete, published translations are visible to the storefront."""
    return stmt.where(
        ProductTranslation.locale == locale,
        ProductTranslation.is_published.is_(True),
        ProductTranslation.is_complete.is_(True),
    )


def _image_payload(img: ProductImage) -> dict:
    return {
        "url": img.url,
        "alt_text": img.alt_text,
        "width": img.width,
        "height": img.height,
        "is_primary": img.is_primary,
        "position": img.position,
    }


def _variant_payload(v: ProductVariant) -> dict:
    return {
        "id": v.id,
        "sku": v.sku,
        "variant_title": v.variant_title,
        "size": v.size,
        "size_system": v.size_system,
        "color": v.color,
        "material": v.material,
        "price": str(v.price),
        "sale_price": str(v.sale_price) if v.sale_price is not None else None,
        "currency": v.currency,
        "availability": v.availability.value
        if hasattr(v.availability, "value")
        else v.availability,
        "stock_quantity": v.stock_quantity,
        "gtin": v.gtin,
    }


def get_product_by_slug(db: Session, locale: str, slug: str) -> dict | None:
    """Product detail for one locale, read through the cache."""

    def load() -> dict | None:
        tr = db.execute(
            _published(select(ProductTranslation), locale).where(
                ProductTranslation.slug == slug
            )
        ).scalar_one_or_none()
        if tr is None:
            return None

        product = db.execute(
            select(Product)
            .where(Product.id == tr.product_id, Product.status == "active")
            .options(
                selectinload(Product.variants),
                selectinload(Product.images),
                selectinload(Product.category),
            )
        ).scalar_one_or_none()
        if product is None:
            return None

        # hreflang cluster: only locales with a published, complete translation.
        alternates = {
            row.locale: f"/{row.locale}/products/{row.slug}"
            for row in db.execute(
                select(ProductTranslation).where(
                    ProductTranslation.product_id == product.id,
                    ProductTranslation.is_published.is_(True),
                    ProductTranslation.is_complete.is_(True),
                )
            ).scalars()
        }
        # A cluster of one emits nothing — never claim an alternate that is not
        # genuinely published in that language.
        if len(alternates) < 2:
            alternates = {}

        cat_tr = None
        if product.category_id:
            cat_tr = db.execute(
                select(CategoryTranslation).where(
                    CategoryTranslation.category_id == product.category_id,
                    CategoryTranslation.locale == locale,
                )
            ).scalar_one_or_none()

        active_variants = [v for v in product.variants if v.is_active]
        default_sku = next(
            (v.sku for v in active_variants if v.id == product.default_variant_id), None
        )

        return {
            "id": product.id,
            "slug": tr.slug,
            "locale": locale,
            "title": tr.title,
            "description": tr.description,
            "brand": product.brand,
            "item_group_id": product.item_group_id,
            "category_slug": cat_tr.slug if cat_tr else None,
            "category_name": cat_tr.title if cat_tr else None,
            "product_type": product.product_type,
            "condition": product.condition.value
            if hasattr(product.condition, "value")
            else product.condition,
            "tags": list(product.tags or []),
            "seo_title": tr.seo_title or tr.title,
            "meta_description": tr.meta_description,
            "is_indexable": bool(tr.robots_index and product.is_indexable),
            "canonical_url": tr.canonical_override
            or f"/{locale}/products/{tr.slug}",
            "og_title": tr.og_title,
            "og_description": tr.og_description,
            "og_image_url": tr.og_image_url,
            "alternates": alternates,
            "images": [
                _image_payload(i)
                for i in sorted(product.images, key=lambda i: i.position)
            ],
            "variants": [_variant_payload(v) for v in active_variants],
            "default_variant_sku": default_sku,
        }

    # TTL_PRICING, not TTL_CONTENT — this payload carries price and stock.
    return cache.get_or_set(
        cache.key(cache.NS_PRODUCT, locale, slug), load, ttl=cache.TTL_PRICING
    )


def list_products(
    db: Session,
    locale: str,
    page: int = 1,
    page_size: int = 24,
    category_slug: str | None = None,
    collection_slug: str | None = None,
) -> dict:
    """Paged listing, optionally scoped to a category or a collection.

    ``item_list_id`` / ``item_list_name`` are returned alongside the items so
    the frontend can emit section 5's ``view_item_list`` with the same list
    identity that will later be stamped onto the cart and order lines.
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    offset = (page - 1) * page_size

    def load() -> dict:
        stmt = (
            select(ProductTranslation, Product)
            .join(Product, Product.id == ProductTranslation.product_id)
            .where(Product.status == "active")
        )
        stmt = _published(stmt, locale)

        list_id = list_name = None

        if category_slug:
            stmt = stmt.join(Category, Category.id == Product.category_id).join(
                CategoryTranslation,
                (CategoryTranslation.category_id == Category.id)
                & (CategoryTranslation.locale == locale),
            ).where(CategoryTranslation.slug == category_slug)
            cat = db.execute(
                select(Category)
                .join(
                    CategoryTranslation,
                    (CategoryTranslation.category_id == Category.id)
                    & (CategoryTranslation.locale == locale),
                )
                .where(CategoryTranslation.slug == category_slug)
            ).scalar_one_or_none()
            if cat:
                list_id, list_name = cat.list_id, cat.name

        if collection_slug:
            stmt = stmt.join(
                CollectionProduct, CollectionProduct.product_id == Product.id
            ).join(
                Collection, Collection.id == CollectionProduct.collection_id
            ).where(Collection.slug == collection_slug)
            coll = db.execute(
                select(Collection).where(Collection.slug == collection_slug)
            ).scalar_one_or_none()
            if coll:
                list_id, list_name = coll.list_id, coll.name

        total = db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        rows = db.execute(
            stmt.order_by(Product.id).offset(offset).limit(page_size)
        ).all()

        # Batched, not per-row. This loop previously issued two queries per
        # product (variants, then the primary image), so a 24-item page cost 49
        # round trips. The cache hid it right up until a cold page under load.
        # Two grouped queries keep the listing O(1) in query count.
        product_ids = [p.id for _, p in rows]

        cheapest_by_product: dict[int, ProductVariant] = {}
        if product_ids:
            for variant in db.execute(
                select(ProductVariant)
                .where(
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.is_active.is_(True),
                )
                .order_by(ProductVariant.product_id, ProductVariant.price)
            ).scalars():
                # Ordered by price, so the first row per product is the cheapest.
                cheapest_by_product.setdefault(variant.product_id, variant)

        primary_by_product: dict[int, ProductImage] = {}
        if product_ids:
            for image in db.execute(
                select(ProductImage).where(
                    ProductImage.product_id.in_(product_ids),
                    ProductImage.is_primary.is_(True),
                    ProductImage.variant_id.is_(None),
                )
            ).scalars():
                primary_by_product.setdefault(image.product_id, image)

        items = []
        for index, (tr, product) in enumerate(rows, start=offset):
            cheapest = cheapest_by_product.get(product.id)
            primary = primary_by_product.get(product.id)

            items.append(
                {
                    "id": product.id,
                    "slug": tr.slug,
                    "title": tr.title,
                    "brand": product.brand,
                    "item_group_id": product.item_group_id,
                    # The sellable identifier, and the same value GA4 and Ads
                    # use (section 2). It is the CHEAPEST variant's SKU because
                    # that is the variant whose price this row advertises --
                    # any other would show one price and identify a different
                    # item. Without it, view_item_list and select_item carry no
                    # item_id and every join from impression to revenue breaks.
                    "sku": cheapest.sku if cheapest else None,
                    "price": str(cheapest.price) if cheapest else None,
                    "sale_price": str(cheapest.sale_price)
                    if cheapest and cheapest.sale_price is not None
                    else None,
                    "currency": "EGP",
                    "primary_image": _image_payload(primary) if primary else None,
                    "item_list_id": list_id,
                    "item_list_name": list_name,
                    "index": index,
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "item_list_id": list_id,
            "item_list_name": list_name,
        }

    ckey = cache.key(
        cache.NS_LISTING,
        locale,
        category_slug or "-",
        collection_slug or "-",
        page,
        page_size,
    )
    return cache.get_or_set(ckey, load, ttl=cache.TTL_PRICING)
