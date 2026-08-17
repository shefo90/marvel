"""Minimal bilingual seed so the catalog API can be exercised.

Creates: both locales, one category branch (Shoes -> Sandals), one collection
("Summer Edit"), and two products — one published in both locales, one published
in English only. That second product is the interesting case: it must 404 under
/ar/ and emit no hreflang, rather than falling back to English.

Idempotent. Run from the backend root:  python scripts/seed.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from models.categories import Category  # noqa: E402
from models.category_translations import CategoryTranslation  # noqa: E402
from models.collection_products import CollectionProduct  # noqa: E402
from models.collection_translations import CollectionTranslation  # noqa: E402
from models.collections import Collection  # noqa: E402
from models.locales import Locale  # noqa: E402
from models.product_images import ProductImage  # noqa: E402
from models.product_translations import ProductTranslation  # noqa: E402
from models.product_variants import ProductVariant  # noqa: E402
from models.products import Product  # noqa: E402

db = SessionLocal()


def get_or_create(model, defaults=None, **filters):
    row = db.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if row:
        return row, False
    row = model(**filters, **(defaults or {}))
    db.add(row)
    db.flush()
    return row, True


# --- Locales -------------------------------------------------------------
get_or_create(
    Locale,
    {
        "hreflang": "en",
        "name_native": "English",
        "text_direction": "ltr",
        "is_default": True,
        "sort_order": 1,
    },
    code="en",
)
get_or_create(
    Locale,
    {
        "hreflang": "ar",
        "name_native": "العربية",
        "text_direction": "rtl",
        "is_default": False,
        "sort_order": 2,
    },
    code="ar",
)

# --- Category branch -----------------------------------------------------
shoes, _ = get_or_create(
    Category, {"level": 1, "name": "Shoes", "list_id": "cat_shoes", "position": 1}, slug="shoes"
)
sandals, _ = get_or_create(
    Category,
    {"level": 2, "parent_id": shoes.id, "name": "Sandals", "list_id": "cat_sandals", "position": 1},
    slug="sandals",
)

for cat, loc, title, slug in [
    (shoes, "en", "Shoes", "shoes"),
    (shoes, "ar", "أحذية", "احذية"),
    (sandals, "en", "Sandals", "sandals"),
    (sandals, "ar", "صنادل", "صنادل"),
]:
    get_or_create(
        CategoryTranslation,
        {
            "title": title,
            "slug": slug,
            "description": f"{title} collection",
            "meta_description": f"Shop {title}",
            "is_published": True,
        },
        category_id=cat.id,
        locale=loc,
    )

# --- Collection ("Summer Edit") -> section 5 item_list_id ----------------
summer, _ = get_or_create(
    Collection, {"list_id": "summer_edit", "name": "Summer Edit", "position": 1}, slug="summer-edit"
)
for loc, title, slug in [("en", "Summer Edit", "summer-edit"), ("ar", "إصدار الصيف", "اصدار-الصيف")]:
    get_or_create(
        CollectionTranslation,
        {
            "title": title,
            "slug": slug,
            "description": f"{title} picks",
            "meta_description": title,
            "is_published": True,
        },
        collection_id=summer.id,
        locale=loc,
    )


def make_product(item_group, base_slug, en, ar, sizes, color, price, cost):
    product, created = get_or_create(
        Product,
        {
            "item_group_id": item_group,
            "title": en["title"],
            "brand": "Pixi",
            "category_id": sandals.id,
            "product_type": "Shoes > Sandals",
            "tags": ["summer", "leather"],
            "description": en["description"],
        },
        slug=base_slug,
    )

    for size in sizes:
        sku = f"{item_group}-{color[:3].upper()}-{size}"
        variant, _ = get_or_create(
            ProductVariant,
            {
                "product_id": product.id,
                "variant_title": f"{color.title()} / {size}",
                "size": str(size),
                "size_system": "EU",
                "color": color,
                "price": price,
                "cost": cost,
                "stock_quantity": 12,
            },
            sku=sku,
        )
        if product.default_variant_id is None:
            product.default_variant_id = variant.id

    get_or_create(
        ProductImage,
        {
            "alt_text": en["title"],
            "width": 1200,
            "height": 1600,
            "is_primary": True,
            "position": 0,
        },
        product_id=product.id,
        url=f"https://cdn.example.com/{base_slug}.jpg",
    )

    for loc, content in (("en", en), ("ar", ar)):
        if content is None:
            continue
        get_or_create(
            ProductTranslation,
            {
                "title": content["title"],
                "description": content["description"],
                "meta_description": content["meta"],
                "seo_title": content["title"],
                "is_published": True,
            },
            product_id=product.id,
            locale=loc,
            slug=content["slug"],
        )

    get_or_create(CollectionProduct, {"position": product.id}, collection_id=summer.id, product_id=product.id)

    product.status = "active"
    db.flush()
    return product


make_product(
    "PX-SANDAL-01",
    "leather-strap-sandal",
    {
        "title": "Leather Strap Sandal",
        "slug": "leather-strap-sandal",
        "description": "A soft leather sandal with an adjustable ankle strap.",
        "meta": "Shop the Leather Strap Sandal in black leather.",
    },
    {
        "title": "صندل جلد بحزام",
        "slug": "صندل-جلد-بحزام",
        "description": "صندل من الجلد الناعم بحزام قابل للتعديل حول الكاحل.",
        "meta": "تسوقي صندل الجلد بحزام باللون الأسود.",
    },
    [37, 38, 39],
    "black",
    1299.00,
    540.00,
)

# English only — must 404 under /ar/ and emit no hreflang.
make_product(
    "PX-SANDAL-02",
    "woven-flat-sandal",
    {
        "title": "Woven Flat Sandal",
        "slug": "woven-flat-sandal",
        "description": "A woven flat sandal for everyday wear.",
        "meta": "Shop the Woven Flat Sandal.",
    },
    None,
    [38, 39],
    "beige",
    999.00,
    410.00,
)

db.commit()

print("locales:      ", db.execute(select(Locale)).scalars().all().__len__())
print("categories:   ", db.execute(select(Category)).scalars().all().__len__())
print("products:     ", db.execute(select(Product)).scalars().all().__len__())
print("variants:     ", db.execute(select(ProductVariant)).scalars().all().__len__())
print("translations: ", db.execute(select(ProductTranslation)).scalars().all().__len__())
db.close()
