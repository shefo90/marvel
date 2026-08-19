"""A catalogue big enough to look at, with generated placeholder imagery.

The storefront had two products whose image URLs pointed at ``cdn.example.com``,
so every page rendered two broken images. No amount of styling reads as a shop
in that state, and filters and facets cannot be judged against two rows.

This creates products across the seeded categories, each with variants in
several sizes and colours, some marked down, and two images apiece so the card's
hover swap has something to swap to.

**The imagery is generated here, not fetched.** Each file is a plain tinted
panel carrying the product's own name, drawn with Pillow at upload time. That
keeps the repository free of binary assets, makes every run reproducible, and
means nothing here has to be replaced for licensing reasons -- when real
photography arrives it is uploaded through the same admin screen and these rows
are replaced one by one.

The bytes go through ``repositories.admin_images.add_image``, the same path the
admin uses: validated, re-encoded, three derivatives, content-addressed storage.
Seeding past it would prove nothing about the pipeline the shop actually serves
from.

Idempotent. Run after seed_taxonomy.py, from the backend root:

    python scripts/seed_demo_catalogue.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from models.categories import Category  # noqa: E402
from models.collection_products import CollectionProduct  # noqa: E402
from models.collections import Collection  # noqa: E402
from models.product_images import ProductImage  # noqa: E402
from models.products import Product  # noqa: E402
from models.users import User  # noqa: E402
from repositories.admin_catalog import (  # noqa: E402
    create_product,
    generate_variants,
    publish_product,
    update_variant,
    upsert_translation,
)
from repositories.admin_images import add_image  # noqa: E402
from repositories.taxonomy import invalidate_taxonomy  # noqa: E402
from services.cache_invalidation import run_pending  # noqa: E402

db = SessionLocal()

# Tints for the generated panels, keyed by the colour code the variant carries,
# so a "black" product reads dark and a "beige" one reads pale. Purely cosmetic.
SWATCH = {
    "black": (34, 32, 30), "white": (242, 240, 236), "beige": (214, 198, 176),
    "brown": (94, 68, 48), "tan": (176, 133, 92), "navy": (38, 48, 76),
    "grey": (128, 126, 122), "red": (150, 46, 44), "pink": (214, 160, 170),
    "green": (74, 96, 74), "gold": (186, 154, 84), "silver": (186, 186, 190),
}

# (slug, English, Arabic, price, sale price or None, sizes, colours)
CATALOGUE = {
    "sandals": [
        ("crossover-sandal", "Crossover Sandal", "صندل متقاطع", "899.00", "649.00",
         ["36", "37", "38", "39", "40"], ["black", "tan", "gold"]),
        ("braided-slide", "Braided Slide", "صندل مضفر", "749.00", None,
         ["37", "38", "39", "40"], ["beige", "brown"]),
        ("ankle-strap-sandal", "Ankle Strap Sandal", "صندل بحزام كاحل", "1099.00", None,
         ["36", "37", "38", "39"], ["black", "red"]),
    ],
    "slippers": [
        ("padded-slipper", "Padded Slipper", "شبشب مبطن", "549.00", "399.00",
         ["36", "37", "38", "39", "40", "41"], ["pink", "grey", "black"]),
        ("terry-slide", "Terry Slide", "شبشب قطني", "479.00", None,
         ["37", "38", "39", "40"], ["white", "beige"]),
    ],
    "flats": [
        ("pointed-flat", "Pointed Flat", "حذاء فلات مدبب", "1199.00", None,
         ["36", "37", "38", "39", "40"], ["black", "navy", "beige"]),
        ("loafer-flat", "Loafer Flat", "حذاء لوفر", "1349.00", "999.00",
         ["37", "38", "39", "40"], ["brown", "black"]),
    ],
    "ballerinas": [
        ("bow-ballerina", "Bow Ballerina", "باليرينا بفيونكة", "999.00", None,
         ["36", "37", "38", "39"], ["black", "pink"]),
        ("mesh-ballerina", "Mesh Ballerina", "باليرينا شبك", "1049.00", None,
         ["37", "38", "39", "40"], ["beige", "white"]),
    ],
    "heels": [
        ("stiletto-pump", "Stiletto Pump", "حذاء كعب رفيع", "1599.00", "1199.00",
         ["36", "37", "38", "39"], ["black", "red", "gold"]),
        ("block-heel-sandal", "Block Heel Sandal", "صندل كعب عريض", "1449.00", None,
         ["37", "38", "39", "40"], ["tan", "black"]),
        ("kitten-heel-slingback", "Kitten Heel Slingback", "حذاء كعب صغير", "1299.00", None,
         ["36", "37", "38", "39", "40"], ["beige", "navy"]),
    ],
    "sneakers": [
        ("court-sneaker", "Court Sneaker", "حذاء رياضي كلاسيكي", "1699.00", None,
         ["37", "38", "39", "40", "41"], ["white", "silver"]),
        ("runner-sneaker", "Runner Sneaker", "حذاء رياضي للجري", "1849.00", "1399.00",
         ["36", "37", "38", "39", "40", "41"], ["grey", "pink", "black"]),
    ],
    "espadrilles": [
        ("wedge-espadrille", "Wedge Espadrille", "إسبادريل بكعب", "1249.00", None,
         ["36", "37", "38", "39", "40"], ["beige", "navy"]),
    ],
    "handbags": [
        ("structured-tote", "Structured Tote", "شنطة توت", "1899.00", None,
         ["one"], ["black", "tan", "brown"]),
        ("top-handle-bag", "Top Handle Bag", "حقيبة يد بمقبض", "2199.00", "1699.00",
         ["one"], ["black", "red"]),
    ],
    "crossbody": [
        ("quilted-crossbody", "Quilted Crossbody", "حقيبة كروس مبطنة", "1349.00", None,
         ["one"], ["black", "beige", "gold"]),
        ("mini-crossbody", "Mini Crossbody", "حقيبة كروس صغيرة", "999.00", None,
         ["one"], ["pink", "silver"]),
    ],
    "shoulder": [
        ("hobo-shoulder-bag", "Hobo Shoulder Bag", "حقيبة كتف", "1599.00", None,
         ["one"], ["brown", "black"]),
    ],
    "beach-bags": [
        ("straw-beach-bag", "Straw Beach Bag", "حقيبة شاطئ من القش", "849.00", "599.00",
         ["one"], ["beige", "white"]),
    ],
    "clutches": [
        ("evening-clutch", "Evening Clutch", "كلتش سهرة", "1099.00", None,
         ["one"], ["gold", "black", "silver"]),
    ],
    "wallets": [
        ("zip-wallet", "Zip Wallet", "محفظة بسحاب", "649.00", None,
         ["one"], ["black", "brown", "red"]),
    ],
}

# Which collection each product joins, by product slug.
COLLECTION_MEMBERS = {
    "new-arrivals": [
        "crossover-sandal", "pointed-flat", "court-sneaker", "structured-tote",
        "quilted-crossbody", "bow-ballerina",
    ],
    "comfort": ["padded-slipper", "terry-slide", "loafer-flat", "runner-sneaker"],
    "office": ["pointed-flat", "loafer-flat", "structured-tote", "kitten-heel-slingback"],
    "nightlife": ["stiletto-pump", "evening-clutch", "ankle-strap-sandal"],
    "summer": ["braided-slide", "wedge-espadrille", "straw-beach-bag", "crossover-sandal"],
}


def placeholder(text: str, color_code: str, *, variant: int) -> bytes:
    """A tinted panel carrying the product's name. Deliberately obviously not a
    photograph, so nobody mistakes seeded data for the real catalogue."""
    tint = SWATCH.get(color_code, (150, 150, 150))
    # The second image is a shade off the first, so the card's hover swap is
    # visibly a swap rather than looking like a rendering glitch.
    if variant:
        tint = tuple(min(255, channel + 26) for channel in tint)

    image = Image.new("RGB", (1200, 1500), tint)
    draw = ImageDraw.Draw(image)
    luminance = (tint[0] * 299 + tint[1] * 587 + tint[2] * 114) / 1000
    ink = (24, 24, 24) if luminance > 140 else (245, 245, 245)

    draw.rectangle([60, 60, 1140, 1440], outline=ink, width=3)
    lines = [text[i:i + 18] for i in range(0, len(text), 18)]
    y = 700 - (len(lines) * 22)
    for line in lines:
        draw.text((110, y), line, fill=ink)
        y += 44
    draw.text((110, 1360), f"{color_code.upper()} - PLACEHOLDER", fill=ink)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def actor() -> User:
    user = db.execute(
        select(User).where(User.email == "seed@marvel.local")
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email="seed@marvel.local", password_hash="!", full_name="Seed",
            role="admin", is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def category_by_slug(slug: str) -> Category | None:
    return db.execute(select(Category).where(Category.slug == slug)).scalar_one_or_none()


def build(staff, category: Category, spec) -> Product:
    slug, english, arabic, price, sale, sizes, colors = spec

    existing = db.execute(select(Product).where(Product.slug == slug)).scalar_one_or_none()
    if existing is not None:
        return existing

    product = create_product(db, staff, {
        "title": english, "slug": slug, "brand": "Pixi", "category_id": category.id,
    })
    variants = generate_variants(db, staff, product.id, sizes, colors, {
        "price": price, "stock_quantity": 12,
    })
    if sale:
        # Only some variants are marked down, which is the realistic case and
        # the one that makes "from" pricing on the card meaningful.
        for variant in variants[: max(1, len(variants) // 2)]:
            update_variant(db, staff, variant.id, {"sale_price": sale})

    for locale, title in (("en", english), ("ar", arabic)):
        upsert_translation(db, staff, product.id, locale, {
            "title": title,
            "slug": slug if locale == "en" else f"{slug}-ar",
            "description": (
                f"{title} — part of the demo catalogue."
                if locale == "en" else f"{title} — من الكتالوج التجريبي."
            ),
            "meta_description": title,
        })

    for index in range(2):
        add_image(
            db, staff, product.id,
            data=placeholder(english, colors[0], variant=index),
            filename=f"{slug}-{index}.png",
            alt_text=f"{english} in {colors[0]}",
        )

    for locale in ("en", "ar"):
        publish_product(db, staff, product.id, locale)
    return product


def join_collections() -> int:
    joined = 0
    for collection_slug, product_slugs in COLLECTION_MEMBERS.items():
        collection = db.execute(
            select(Collection).where(Collection.slug == collection_slug)
        ).scalar_one_or_none()
        if collection is None:
            continue
        for position, product_slug in enumerate(product_slugs):
            product = db.execute(
                select(Product).where(Product.slug == product_slug)
            ).scalar_one_or_none()
            if product is None:
                continue
            link = db.execute(
                select(CollectionProduct).where(
                    CollectionProduct.collection_id == collection.id,
                    CollectionProduct.product_id == product.id,
                )
            ).scalar_one_or_none()
            if link is None:
                db.add(CollectionProduct(
                    collection_id=collection.id, product_id=product.id,
                    position=position,
                ))
                joined += 1
    return joined


def main() -> None:
    staff = actor()
    created = 0
    skipped = 0

    for category_slug, specs in CATALOGUE.items():
        category = category_by_slug(category_slug)
        if category is None:
            print(f"  ! no category '{category_slug}' — run seed_taxonomy.py first")
            continue
        for spec in specs:
            before = db.execute(
                select(Product).where(Product.slug == spec[0])
            ).scalar_one_or_none()
            build(staff, category, spec)
            if before is None:
                created += 1
                print(f"  + {spec[1]}")
            else:
                skipped += 1

    joined = join_collections()
    db.commit()
    # add_image and the catalog writes queue their cache work; without a worker
    # running, this script is the one that has to drain it.
    run_pending(db)
    invalidate_taxonomy()

    total = db.execute(select(Product)).scalars().all()
    images = db.execute(select(ProductImage)).scalars().all()
    print(f"\nproducts created: {created}, already present: {skipped}")
    print(f"collection memberships added: {joined}")
    print(f"catalogue now holds {len(total)} products and {len(images)} images")


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close()
