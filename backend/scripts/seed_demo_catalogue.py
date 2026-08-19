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

# seed.py's products, which predate this script. (slug, label, silhouette)
LEGACY_SEED = [
    ("leather-strap-sandal", "Leather Strap Sandal", "shoe"),
    ("woven-flat-sandal", "Woven Flat Sandal", "shoe"),
]

# Which silhouette a product's placeholder gets drawn with.
BAG_CATEGORIES = {
    "handbags", "crossbody", "shoulder", "beach-bags", "clutches", "wallets",
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


def _gradient(size, top, bottom):
    """A soft vertical wash, drawn a row at a time."""
    width, height = size
    image = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return image


def _shoe(draw, tint, shade):
    """A side-on heel. Enough shape to read as footwear at thumbnail size."""
    draw.polygon(
        [(300, 980), (880, 980), (900, 900), (760, 860), (600, 700),
         (430, 690), (330, 780)],
        fill=tint,
    )
    draw.polygon([(300, 980), (880, 980), (880, 1010), (300, 1010)], fill=shade)
    # The heel.
    draw.polygon([(800, 1010), (860, 1010), (830, 1200), (790, 1200)], fill=shade)
    draw.ellipse([(430, 660), (630, 740)], fill=shade)


def _bag(draw, tint, shade):
    """A tote: trapezoid body, two handles, a band across the front."""
    draw.polygon([(360, 720), (840, 720), (890, 1180), (310, 1180)], fill=tint)
    draw.rectangle([(310, 920), (890, 985)], fill=shade)
    for offset in (0, 1):
        cx = 480 + offset * 240
        draw.arc([(cx - 90, 560), (cx + 90, 800)], start=180, end=360,
                 fill=shade, width=26)


def placeholder(text: str, color_code: str, *, variant: int, kind: str = "shoe") -> bytes:
    """A drawn stand-in for a product photograph.

    Flat colour panels were technically images and read as missing ones -- a
    grid of them looks like a page that failed to load, which is the opposite of
    what a placeholder should communicate. This draws a silhouette on a lit
    background instead, so a section reads as "products here, photography
    pending" rather than "broken".

    Still deliberately not photographic. Nobody should mistake seeded data for
    the real catalogue, and every one of these is replaced the moment a real
    photograph is uploaded through the admin.
    """
    tint = SWATCH.get(color_code, (150, 150, 150))
    # The second image is lit differently, so the card's hover swap is visibly a
    # swap rather than looking like a rendering glitch.
    top = (250, 247, 242) if not variant else (243, 236, 228)
    bottom = (232, 224, 214) if not variant else (222, 212, 200)

    image = _gradient((1200, 1500), top, bottom)
    draw = ImageDraw.Draw(image)

    shade = tuple(max(0, channel - 34) for channel in tint)
    # A contact shadow, so the silhouette sits on the surface rather than
    # floating on it.
    draw.ellipse([(300, 1150), (900, 1260)], fill=(214, 206, 196))

    if kind == "bag":
        _bag(draw, tint, shade)
    else:
        _shoe(draw, tint, shade)

    draw.text((72, 1420), f"{text} · placeholder", fill=(120, 112, 104))

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

    kind = "bag" if category.slug in BAG_CATEGORIES else "shoe"
    for index in range(2):
        add_image(
            db, staff, product.id,
            data=placeholder(english, colors[0], variant=index, kind=kind),
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


def repair_external_images(staff) -> int:
    """Replace image rows pointing outside /media with generated files.

    The original seed.py wrote URLs at cdn.example.com, a host that does not
    exist. Those rows render as broken images everywhere they appear -- and
    since the category tiles borrow a product's photograph, one broken row took
    a whole section of the homepage down with it.

    Only rows whose URL is not served by this application are touched, so a real
    CDN prefix configured through MEDIA_URL_PREFIX is left alone.
    """
    from services.storage import storage

    prefix = storage.url_prefix
    broken = db.execute(
        select(ProductImage).where(~ProductImage.url.startswith(prefix))
    ).scalars().all()

    repaired = 0
    for image in broken:
        product = db.get(Product, image.product_id)
        if product is None:
            continue
        db.delete(image)
        db.flush()
        add_image(
            db, staff, product.id,
            data=placeholder(product.title or product.slug, "beige", variant=0),
            filename=f"{product.slug}-repaired.png",
            alt_text=product.title or product.slug,
        )
        repaired += 1
    return repaired


def regenerate_placeholders(staff) -> int:
    """Redraw every seeded product's artwork with the current generator.

    Run when the drawing changes. Only products this script owns are touched --
    anything with a photograph an operator uploaded is matched by slug and left
    alone, because it is not in CATALOGUE.
    """
    owned = {slug for specs in CATALOGUE.values() for (slug, *_rest) in specs}
    redrawn = 0

    # seed.py's two products are older than this script and carry the same kind
    # of generated stand-in, so they are redrawn too -- one of them is the first
    # product in `sandals`, which means the Shoes tile and the hero both borrow
    # from it. Anything else an operator has created is deliberately untouched.
    for slug, english, kind in LEGACY_SEED:
        product = db.execute(
            select(Product).where(Product.slug == slug)
        ).scalar_one_or_none()
        if product is None:
            continue
        for image in db.execute(
            select(ProductImage).where(ProductImage.product_id == product.id)
        ).scalars().all():
            db.delete(image)
        db.flush()
        for index in range(2):
            add_image(
                db, staff, product.id,
                data=placeholder(english, "beige", variant=index, kind=kind),
                filename=f"{slug}-{index}.png",
                alt_text=english,
            )
        redrawn += 1

    for category_slug, specs in CATALOGUE.items():
        kind = "bag" if category_slug in BAG_CATEGORIES else "shoe"
        for slug, english, _ar, _price, _sale, _sizes, colors in specs:
            if slug not in owned:
                continue
            product = db.execute(
                select(Product).where(Product.slug == slug)
            ).scalar_one_or_none()
            if product is None:
                continue

            for image in db.execute(
                select(ProductImage).where(ProductImage.product_id == product.id)
            ).scalars().all():
                db.delete(image)
            db.flush()

            for index in range(2):
                add_image(
                    db, staff, product.id,
                    data=placeholder(english, colors[0], variant=index, kind=kind),
                    filename=f"{slug}-{index}.png",
                    alt_text=f"{english} in {colors[0]}",
                )
            redrawn += 1
    return redrawn


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
    redrawn = regenerate_placeholders(staff)
    if redrawn:
        print(f"placeholder artwork redrawn: {redrawn} products")
    repaired = repair_external_images(staff)
    if repaired:
        print(f"\nimage rows repointed from an unreachable host: {repaired}")
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
