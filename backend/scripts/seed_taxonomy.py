"""Seed the browsable structure: the category tree, collections, and the
size/colour values the filter sidebar is built from.

Separate from ``seed.py``, which seeds a couple of products to exercise the
catalog API. This seeds the *shape* of the shop, and it is the shape an operator
is expected to edit afterwards through the admin — every row here is ordinary
data with no special status, so renaming "Sandals" or deleting a colour is a
normal back-office action, not a code change.

**Why the attribute values matter more than they look.** A variant stores the
canonical code ("black", "38"); ``attribute_values`` holds its English label and
``attribute_value_translations`` its Arabic one. Without a row here the browse
API has nothing to translate with and falls back to showing the raw code, so the
Arabic filter sidebar reads "black" and "beige" in Latin script down the side of
an RTL page. ``sort_order`` is the other half: without it sizes sort as text and
"10" lands before "9".

Idempotent. Run from the backend root:  python scripts/seed_taxonomy.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from core.enums import AttributeType  # noqa: E402
from models.attribute_value_translations import AttributeValueTranslation  # noqa: E402
from models.attribute_values import AttributeValue  # noqa: E402
from models.categories import Category  # noqa: E402
from models.category_translations import CategoryTranslation  # noqa: E402
from models.collection_translations import CollectionTranslation  # noqa: E402
from models.collections import Collection  # noqa: E402
from models.locales import Locale  # noqa: E402
from repositories.taxonomy import invalidate_taxonomy  # noqa: E402

db = SessionLocal()


def get_or_create(model, defaults=None, **filters):
    row = db.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    if row:
        return row, False
    row = model(**filters, **(defaults or {}))
    db.add(row)
    db.flush()
    return row, True


# --- the tree ------------------------------------------------------------
# Level 1 -> its level-2 children. Two levels is all the schema can hold:
# categories.parent_level is generated and the self-FK is composite.
TREE = {
    ("shoes", "Shoes", "أحذية"): [
        ("sandals", "Sandals", "صنادل"),
        ("slippers", "Slippers", "شباشب"),
        ("flats", "Flats", "أحذية فلات"),
        ("ballerinas", "Ballerinas", "باليرينا"),
        ("heels", "Heels", "كعب عالي"),
        ("sneakers", "Sneakers", "أحذية رياضية"),
        ("espadrilles", "Espadrilles", "إسبادريل"),
    ],
    ("bags", "Bags", "حقائب"): [
        ("beach-bags", "Beach Bags", "حقائب الشاطئ"),
        ("handbags", "Handbags", "حقائب يد"),
        ("crossbody", "Crossbody", "حقائب كروس"),
        ("shoulder", "Shoulder", "حقائب كتف"),
        ("clutches", "Clutches", "كلتش"),
        ("wallets", "Wallets", "محافظ"),
    ],
}

COLLECTIONS = [
    ("new-arrivals", "New Arrivals", "وصل حديثاً"),
    ("comfort", "Comfort", "الراحة"),
    ("office", "Office", "المكتب"),
    ("nightlife", "Nightlife", "السهرة"),
    ("summer", "Summer", "الصيف"),
]

# EU sizing. sort_order is explicit so the facet reads 35, 36, 37 rather than
# sorting as text.
SIZES = [str(n) for n in range(35, 43)]

# code -> (English label, Arabic label). The code is what a variant stores and
# what a filter sends back; the labels are display only.
COLORS = [
    ("black", "Black", "أسود"),
    ("white", "White", "أبيض"),
    ("beige", "Beige", "بيج"),
    ("brown", "Brown", "بني"),
    ("tan", "Tan", "عسلي"),
    ("navy", "Navy", "كحلي"),
    ("grey", "Grey", "رمادي"),
    ("red", "Red", "أحمر"),
    ("pink", "Pink", "وردي"),
    ("green", "Green", "أخضر"),
    ("gold", "Gold", "ذهبي"),
    ("silver", "Silver", "فضي"),
]


def ensure_locales() -> None:
    for code, name, direction in (("en", "English", "ltr"), ("ar", "العربية", "rtl")):
        get_or_create(
            Locale, code=code,
            defaults={"name": name, "direction": direction, "is_active": True},
        )


def ensure_category(slug, name, arabic, *, parent=None, position=0) -> Category:
    category, created = get_or_create(
        Category, slug=slug,
        defaults={
            "parent_id": parent.id if parent else None,
            "level": 2 if parent else 1,
            "name": name,
            # Never localized: section 5's item_list_id must be the same string
            # on the Arabic and English pages, or one shop's traffic splits in
            # two in every report.
            "list_id": f"cat_{slug.replace('-', '_')}",
            "position": position,
            "is_active": True,
            "is_indexable": True,
        },
    )
    for locale, title in (("en", name), ("ar", arabic)):
        get_or_create(
            CategoryTranslation, category_id=category.id, locale=locale,
            defaults={
                "title": title,
                "slug": slug if locale == "en" else f"{slug}-ar",
                "description": title,
                "meta_description": title,
                "is_published": True,
            },
        )
    return category, created


def ensure_collection(slug, name, arabic, position) -> Collection:
    collection, created = get_or_create(
        Collection, slug=slug,
        defaults={
            "name": name,
            "list_id": slug.replace("-", "_"),
            "position": position,
            "is_active": True,
            "is_indexable": True,
        },
    )
    for locale, title in (("en", name), ("ar", arabic)):
        get_or_create(
            CollectionTranslation, collection_id=collection.id, locale=locale,
            defaults={
                "title": title,
                "slug": slug if locale == "en" else f"{slug}-ar",
                "description": title,
                "meta_description": title,
                "is_published": True,
            },
        )
    return collection, created


def ensure_attribute(kind: AttributeType, code: str, label: str, arabic: str, order: int):
    value, created = get_or_create(
        AttributeValue, attribute_type=kind, code=code,
        defaults={"label": label, "sort_order": order, "is_active": True},
    )
    get_or_create(
        AttributeValueTranslation, attribute_value_id=value.id, locale="ar",
        defaults={"label": arabic},
    )
    return value, created


def main() -> None:
    ensure_locales()

    categories = 0
    for position, ((slug, name, arabic), children) in enumerate(TREE.items()):
        parent, created = ensure_category(slug, name, arabic, position=position)
        categories += created
        for child_position, (child_slug, child_name, child_arabic) in enumerate(children):
            _, child_created = ensure_category(
                child_slug, child_name, child_arabic,
                parent=parent, position=child_position,
            )
            categories += child_created

    collections = 0
    for position, (slug, name, arabic) in enumerate(COLLECTIONS):
        _, created = ensure_collection(slug, name, arabic, position)
        collections += created

    attributes = 0
    for order, size in enumerate(SIZES):
        # A size's label is the same in both scripts: section 6.6 requires
        # Western digits in Arabic too, so "٣٨" would be wrong here.
        _, created = ensure_attribute(AttributeType.size, size, size, size, order)
        attributes += created
    for order, (code, label, arabic) in enumerate(COLORS):
        _, created = ensure_attribute(AttributeType.color, code, label, arabic, order)
        attributes += created

    db.commit()
    # The menu caches for six hours; without this the shop would not show any of
    # the above until it expired.
    invalidate_taxonomy()

    print(f"categories created: {categories}")
    print(f"collections created: {collections}")
    print(f"attribute values created: {attributes}")
    print("re-run is a no-op — every row is looked up before it is created")


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close()
