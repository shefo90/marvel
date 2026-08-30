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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from models.attribute_value_translations import AttributeValueTranslation
from models.attribute_values import AttributeValue
from models.categories import Category
from models.category_translations import CategoryTranslation
from models.collections import Collection
from models.collection_products import CollectionProduct
from models.collection_translations import CollectionTranslation
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


SORTS = ("featured", "newest", "price_asc", "price_desc")


def _effective_price():
    """What the card actually shows. A markdown is the price a shopper sees, so
    filtering and sorting must both use it -- sorting by list price while
    displaying the sale price puts the cheapest-looking item halfway down."""
    return func.coalesce(ProductVariant.sale_price, ProductVariant.price)


def _matches_query(q: str, locale: str):
    """The search predicate: stemmed words, then prefixes, then near-misses.

    Three clauses because they answer three different shopper behaviours and
    none of them subsumes the others:

    - ``search_vector @@ plainto_tsquery`` matches whole words with stemming, so
      an English "sandals" finds a "Sandal" and the Arabic stemmer earns its
      keep. It cannot match a partial word.
    - ``LIKE '%...%'`` on the folded text matches prefixes and mid-word
      fragments -- somebody typing "espad" before they have finished. The GIN
      trigram index services this; it is not a sequential scan.
    - ``word_similarity() > 0.5`` catches typos ("sandel" for "sandal").

    **It has to be ``word_similarity`` and not ``similarity``**, and the
    difference is not academic. ``similarity`` compares the query against the
    *whole* stored document, so a six-letter word measured against a
    seventy-character title-plus-description scores 0.08 -- below any usable
    threshold. ``word_similarity`` scores the query against the best-matching
    run of words inside the document, which for the same pair is 0.57. The first
    version of this used ``similarity`` and passed its unit test only because
    that test's fixture had a one-word description; against the real catalogue
    "sandel" returned nothing at all. The threshold is 0.5 rather than pg_trgm's
    0.6 default because 0.571 is what a single substituted letter costs.

    Brand is matched separately because it lives on ``products`` and a generated
    column cannot reach another table. It has its own expression index.

    The query is folded with the same ``marvel_fold`` the stored columns were
    built with. That is the one invariant search cannot survive breaking, and it
    is why the function is called on both sides rather than reimplemented in
    Python.
    """
    folded = func.marvel_fold(q)
    config = "arabic" if locale == "ar" else "english"

    return or_(
        ProductTranslation.search_vector.op("@@")(
            func.plainto_tsquery(config, folded)
        ),
        ProductTranslation.search_text.like(func.concat("%", folded, "%")),
        func.word_similarity(folded, ProductTranslation.search_text) > 0.5,
        func.marvel_fold(Product.brand).like(func.concat("%", folded, "%")),
    )


def _variant_exists(sizes, colors, in_stock, min_price, max_price):
    """A product matches when ONE active variant satisfies every filter at once.

    Jointly, not independently. Asking for a black 38 and being shown a product
    whose 38 comes only in red is the kind of near-miss that costs a sale twice:
    once when the shopper clicks, and again when they stop trusting the filter.
    """
    conditions = [
        ProductVariant.product_id == Product.id,
        ProductVariant.is_active.is_(True),
    ]
    if sizes:
        conditions.append(ProductVariant.size.in_(sizes))
    if colors:
        conditions.append(ProductVariant.color.in_(colors))
    if in_stock:
        conditions.append(ProductVariant.stock_quantity > 0)
    if min_price is not None:
        conditions.append(_effective_price() >= min_price)
    if max_price is not None:
        conditions.append(_effective_price() <= max_price)
    return select(1).where(*conditions).exists()


def _attribute_labels(db: Session, locale: str) -> dict:
    """(type, code) -> localized label, plus the sort order the operator set.

    Sizes must read 36, 37, 38 rather than sorting as text, where "10" lands
    before "9". ``sort_order`` is what makes that the operator's decision rather
    than a guess about numbering.
    """
    rows = db.execute(
        select(AttributeValue, AttributeValueTranslation.label)
        .outerjoin(
            AttributeValueTranslation,
            (AttributeValueTranslation.attribute_value_id == AttributeValue.id)
            & (AttributeValueTranslation.locale == locale),
        )
        .where(AttributeValue.is_active.is_(True))
    ).all()
    out = {}
    for value, translated in rows:
        kind = value.attribute_type
        kind = kind.value if hasattr(kind, "value") else kind
        out[(kind, value.code)] = {
            "label": translated or value.label,
            "sort_order": value.sort_order,
        }
    return out


def list_products(
    db: Session,
    locale: str,
    page: int = 1,
    page_size: int = 24,
    category_slug: str | None = None,
    collection_slug: str | None = None,
    sizes: list[str] | None = None,
    colors: list[str] | None = None,
    min_price=None,
    max_price=None,
    in_stock: bool = False,
    sort: str = "featured",
    q: str | None = None,
) -> dict:
    """Paged, filtered, sorted listing — the query behind every browse page.

    ``item_list_id`` / ``item_list_name`` are returned alongside the items so
    the frontend can emit section 5's ``view_item_list`` with the same list
    identity that will later be stamped onto the cart and order lines.

    **Facet counts exclude their own facet.** The size counts are computed with
    the colour and price filters applied but the size filter ignored, and vice
    versa. Include a facet in its own count and every unticked box in it reads
    zero the moment one is ticked, which tells the shopper the opposite of the
    truth: those boxes are exactly the ones that would widen the result.
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    offset = (page - 1) * page_size
    sizes = sorted(set(sizes or []))
    colors = sorted(set(colors or []))
    sort = sort if sort in SORTS else "featured"

    def load() -> dict:
        list_id = list_name = None
        collection_join = False
        category_ids: list[int] | None = None

        if category_slug:
            cat = db.execute(
                select(Category)
                .join(
                    CategoryTranslation,
                    (CategoryTranslation.category_id == Category.id)
                    & (CategoryTranslation.locale == locale),
                )
                .where(CategoryTranslation.slug == category_slug)
            ).scalar_one_or_none()

            if cat is None:
                # An unknown slug matches nothing. Not "everything": a typo in a
                # category URL must not quietly render the whole catalogue.
                category_ids = []
            else:
                list_id, list_name = cat.list_id, cat.name
                category_ids = [cat.id]
                if cat.level == 1:
                    # A level-1 category owns no products and never can --
                    # products.category_level is generated as 2 with a composite
                    # FK, so every product hangs off a level-2 category. Matching
                    # only the named row therefore made "Shoes" an empty page
                    # while "Sandals" worked, which is what "View all" hit.
                    category_ids += list(
                        db.execute(
                            select(Category.id).where(Category.parent_id == cat.id)
                        ).scalars()
                    )

        def scoped(*, ignore: str | None = None):
            """The base query, optionally with one facet's own filter removed."""
            stmt = (
                select(ProductTranslation, Product)
                .join(Product, Product.id == ProductTranslation.product_id)
                .where(Product.status == "active")
            )
            stmt = _published(stmt, locale)
            if category_ids is not None:
                stmt = stmt.where(Product.category_id.in_(category_ids))
            if collection_slug:
                # Collection.slug is the base, never-translated identifier --
                # matching it against a URL slug is exactly the bug that made
                # "Shoes" 404 for categories with a real Arabic slug. A
                # collection page is reached by its per-locale translated
                # slug, so that is what has to be matched here too.
                stmt = stmt.join(
                    CollectionProduct, CollectionProduct.product_id == Product.id
                ).join(
                    Collection, Collection.id == CollectionProduct.collection_id
                ).join(
                    CollectionTranslation,
                    (CollectionTranslation.collection_id == Collection.id)
                    & (CollectionTranslation.locale == locale),
                ).where(CollectionTranslation.slug == collection_slug)
            if q:
                stmt = stmt.where(_matches_query(q, locale))
            return stmt.where(
                _variant_exists(
                    None if ignore == "size" else sizes,
                    None if ignore == "color" else colors,
                    in_stock,
                    min_price,
                    max_price,
                )
            )

        if collection_slug:
            collection_join = True
            coll = db.execute(
                select(Collection)
                .join(
                    CollectionTranslation,
                    (CollectionTranslation.collection_id == Collection.id)
                    & (CollectionTranslation.locale == locale),
                )
                .where(CollectionTranslation.slug == collection_slug)
            ).scalar_one_or_none()
            if coll:
                list_id, list_name = coll.list_id, coll.name

        stmt = scoped()

        # Cheapest active variant per product, as a joinable subquery. Needed in
        # the ORDER BY, which a post-query Python sort cannot do without pulling
        # the whole catalog back to sort one page of it.
        from_price = (
            select(
                ProductVariant.product_id.label("product_id"),
                func.min(_effective_price()).label("from_price"),
            )
            .where(ProductVariant.is_active.is_(True))
            .group_by(ProductVariant.product_id)
            .subquery()
        )

        total = db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        ordered = stmt.join(from_price, from_price.c.product_id == Product.id)
        if sort == "price_asc":
            ordered = ordered.order_by(from_price.c.from_price.asc(), Product.id)
        elif sort == "price_desc":
            ordered = ordered.order_by(from_price.c.from_price.desc(), Product.id)
        elif sort == "newest":
            ordered = ordered.order_by(Product.created_at.desc(), Product.id)
        elif collection_join:
            # "Featured" inside a collection is the order the operator arranged
            # it in -- that is what a collection is for.
            ordered = ordered.order_by(CollectionProduct.position, Product.id)
        else:
            # Everywhere else there is no manual order to honour, so featured
            # means newest. Stated plainly because "featured" implying "newest"
            # is a guess otherwise.
            ordered = ordered.order_by(Product.created_at.desc(), Product.id)

        rows = db.execute(ordered.offset(offset).limit(page_size)).all()

        # Batched, not per-row. This loop previously issued two queries per
        # product (variants, then the primary image), so a 24-item page cost 49
        # round trips. The cache hid it right up until a cold page under load.
        product_ids = [p.id for _, p in rows]

        cheapest_by_product: dict[int, ProductVariant] = {}
        swatches_by_product: dict[int, list] = {}
        sizes_by_product: dict[int, list] = {}
        if product_ids:
            for variant in db.execute(
                select(ProductVariant)
                .where(
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.is_active.is_(True),
                )
                .order_by(
                    ProductVariant.product_id,
                    func.coalesce(ProductVariant.sale_price, ProductVariant.price),
                )
            ).scalars():
                # Ordered by effective price, so the first row per product is
                # the one whose price the card advertises.
                cheapest_by_product.setdefault(variant.product_id, variant)
                if variant.color:
                    swatches_by_product.setdefault(variant.product_id, [])
                    if variant.color not in swatches_by_product[variant.product_id]:
                        swatches_by_product[variant.product_id].append(variant.color)
                if variant.size and variant.stock_quantity > 0:
                    sizes_by_product.setdefault(variant.product_id, [])
                    if variant.size not in sizes_by_product[variant.product_id]:
                        sizes_by_product[variant.product_id].append(variant.size)

        # Two images per product: the primary, and the next one in position
        # order for the hover swap. One query, not two per card.
        images_by_product: dict[int, list[ProductImage]] = {}
        if product_ids:
            for image in db.execute(
                select(ProductImage)
                .where(
                    ProductImage.product_id.in_(product_ids),
                    ProductImage.variant_id.is_(None),
                )
                .order_by(
                    ProductImage.product_id,
                    ProductImage.is_primary.desc(),
                    ProductImage.position,
                )
            ).scalars():
                images_by_product.setdefault(image.product_id, []).append(image)

        labels = _attribute_labels(db, locale)

        def _label(kind: str, code: str) -> str:
            entry = labels.get((kind, code))
            return entry["label"] if entry else code

        items = []
        for index, (tr, product) in enumerate(rows, start=offset):
            cheapest = cheapest_by_product.get(product.id)
            gallery = images_by_product.get(product.id, [])
            product_sizes = sizes_by_product.get(product.id, [])
            product_sizes.sort(
                key=lambda code: (
                    labels.get(("size", code), {}).get("sort_order", 9999),
                    code,
                )
            )

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
                    "primary_image": _image_payload(gallery[0]) if gallery else None,
                    # The card swaps to this on hover. Null when the product has
                    # only one photograph, so the frontend does not have to
                    # guess whether a swap is available.
                    "hover_image": _image_payload(gallery[1])
                    if len(gallery) > 1
                    else None,
                    "colors": [
                        {"code": code, "label": _label("color", code)}
                        for code in swatches_by_product.get(product.id, [])
                    ],
                    "sizes": [
                        {"code": code, "label": _label("size", code)}
                        for code in product_sizes
                    ],
                    "item_list_id": list_id,
                    "item_list_name": list_name,
                    "index": index,
                }
            )

        # Built from the scoped product ids rather than reusing `scoped`
        # directly, because the count must be over DISTINCT products while the
        # grouping is over variant values.
        def facet_values(kind: str, column) -> list[dict]:
            inner = scoped(ignore=kind).with_only_columns(Product.id).subquery()
            rows = db.execute(
                select(column, func.count(func.distinct(ProductVariant.product_id)))
                .join(inner, inner.c.id == ProductVariant.product_id)
                .where(
                    column.is_not(None),
                    ProductVariant.is_active.is_(True),
                    *([ProductVariant.stock_quantity > 0] if in_stock else []),
                )
                .group_by(column)
            ).all()
            values = [
                {
                    "code": code,
                    "label": _label(kind, code),
                    "count": count,
                    "selected": code in (sizes if kind == "size" else colors),
                }
                for code, count in rows
            ]
            values.sort(
                key=lambda v: (
                    labels.get((kind, v["code"]), {}).get("sort_order", 9999),
                    v["code"],
                )
            )
            return values

        priced = scoped().with_only_columns(Product.id).subquery()
        bounds = db.execute(
            select(func.min(_effective_price()), func.max(_effective_price()))
            .join(priced, priced.c.id == ProductVariant.product_id)
            .where(ProductVariant.is_active.is_(True))
        ).one_or_none()

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "item_list_id": list_id,
            "item_list_name": list_name,
            "sort": sort,
            "facets": {
                "sizes": facet_values("size", ProductVariant.size),
                "colors": facet_values("color", ProductVariant.color),
                "price": {
                    "min": str(bounds[0]) if bounds and bounds[0] is not None else None,
                    "max": str(bounds[1]) if bounds and bounds[1] is not None else None,
                },
            },
        }

    if q:
        # Not cached, deliberately. A search term is unbounded key space: most
        # queries are typed once and never again, so caching them fills Redis
        # with single-use entries and evicts the category pages that are hit
        # thousands of times. The indexes are what make this fast.
        return load()

    ckey = cache.key(
        cache.NS_LISTING,
        locale,
        category_slug or "-",
        collection_slug or "-",
        # Every filter belongs in the key. Leaving one out serves a filtered
        # page to a shopper who asked for a different filter -- the same class
        # of bug as leaving the locale out, and just as invisible in testing.
        ",".join(sizes) or "-",
        ",".join(colors) or "-",
        min_price if min_price is not None else "-",
        max_price if max_price is not None else "-",
        "instock" if in_stock else "-",
        sort,
        page,
        page_size,
    )
    return cache.get_or_set(ckey, load, ttl=cache.TTL_PRICING)
