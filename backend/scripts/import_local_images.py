"""Import product photography from local folders through the real image pipeline.

Point it at a folder of shoe photographs and a folder of bag photographs and it
assigns them to the matching products, two apiece, so the card's hover swap has
something to swap to.

**This replaced the fetched-from-the-internet experiment**, which is documented
in ``fetch_sample_images.py``: a general media archive returns a landscape for
"sandal" and, worse, a competitor's branded product. Supplied files sidestep
every part of that -- the person supplying them knows what they depict and under
what terms.

The bytes go through ``repositories.admin_images.add_image``, the same path the
admin screen uses: decoded, re-encoded, EXIF stripped, three derivatives written
to content-addressed storage. Seeding past it would prove nothing about the
pipeline the shop actually serves from, and EXIF matters here in particular --
photographs off a camera or phone carry location and device metadata that has no
business being published.

Storage is content-addressed, so importing the same photograph twice writes one
file. Duplicates in the source folders cost nothing.

Usage, from the backend root:

    python scripts/import_local_images.py <shoes-folder> <bags-folder>

Both arguments are optional; omit one to import only the other.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from models.categories import Category  # noqa: E402
from models.product_images import ProductImage  # noqa: E402
from models.products import Product  # noqa: E402
from models.users import User  # noqa: E402
from repositories.admin_images import add_image  # noqa: E402
from repositories.taxonomy import invalidate_taxonomy  # noqa: E402
from services import cache  # noqa: E402
from services.cache_invalidation import run_pending  # noqa: E402

db = SessionLocal()

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

BAG_CATEGORIES = {
    "handbags", "crossbody", "shoulder", "beach-bags", "clutches", "wallets",
}

DEFAULTS = {
    "shoes": os.path.join("..", "storefront", "assets", "shoes images"),
    "bags": os.path.join("..", "storefront", "assets", "bags"),
}


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


def read_folder(path: str) -> list[tuple[str, bytes]]:
    if not path or not os.path.isdir(path):
        print(f"  ! not a folder: {path}")
        return []
    files = []
    for name in sorted(os.listdir(path)):
        if os.path.splitext(name)[1].lower() not in SUFFIXES:
            continue
        with open(os.path.join(path, name), "rb") as handle:
            files.append((name, handle.read()))
    return files


def products_by_kind() -> dict[str, list[Product]]:
    """Every active product, split by whether its category holds bags.

    Keyed off the category slug rather than the product, because a product does
    not know what kind of thing it is -- its category does.
    """
    rows = db.execute(
        select(Product, Category.slug)
        .join(Category, Category.id == Product.category_id)
        .where(Product.status == "active")
        .order_by(Product.id)
    ).all()

    grouped = {"shoes": [], "bags": []}
    for product, category_slug in rows:
        kind = "bags" if category_slug in BAG_CATEGORIES else "shoes"
        grouped[kind].append(product)
    return grouped


def assign(staff, products: list[Product], files: list[tuple[str, bytes]]) -> int:
    """Give each product two photographs, cycling through the pool.

    There are fewer photographs than products, so they repeat. That is honest
    for a demo catalogue and obvious on screen; the alternative -- leaving most
    products blank -- hides the shape of the page being judged.

    The offset walks by two per product so neighbouring cards in a grid do not
    land on the same picture, which is what makes a repeating pool look like a
    bug rather than a placeholder.
    """
    if not products or not files:
        return 0

    done = 0
    for index, product in enumerate(products):
        chosen = [files[(index * 2 + offset) % len(files)] for offset in (0, 1)]

        for image in db.execute(
            select(ProductImage).where(ProductImage.product_id == product.id)
        ).scalars().all():
            db.delete(image)
        db.flush()

        added = 0
        for filename, data in chosen:
            try:
                add_image(
                    db, staff, product.id,
                    data=data,
                    filename=filename,
                    alt_text=product.title or product.slug.replace("-", " "),
                )
                added += 1
            except Exception as exc:  # noqa: BLE001 - one bad file is not a run
                print(f"    ! {product.slug}: {filename} rejected — {exc}")

        if added:
            done += 1
            print(f"    + {product.slug} ({added} image(s))")
    return done


def main() -> None:
    shoes_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULTS["shoes"]
    bags_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULTS["bags"]

    staff = actor()
    grouped = products_by_kind()

    total = 0
    for kind, path in (("shoes", shoes_path), ("bags", bags_path)):
        files = read_folder(path)
        if not files:
            continue
        print(f"\n{kind}: {len(files)} photograph(s) -> "
              f"{len(grouped[kind])} product(s)")
        total += assign(staff, grouped[kind], files)

    db.commit()
    # add_image queues its cache work; without a worker running, this script is
    # the one that has to drain it. The namespaces go too: the category tiles
    # borrow a product's photograph, so they are stale the moment this changes.
    run_pending(db)
    invalidate_taxonomy()
    cache.invalidate_namespace(cache.NS_PRODUCT)
    cache.invalidate_namespace(cache.NS_LISTING)

    print(f"\nproducts given photography: {total}")


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close()
