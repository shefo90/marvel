"""Fetch freely-licensed sample photography from Wikimedia Commons.

**This was tried on 2026-08-20 and the results were not usable. Read this before
running it again.** The script works; the idea does not. Of eleven images it
fetched across six products, the search returned a landscape photograph, a
nineteenth-century oil painting, two museum accession photographs, and a named
competitor's branded product. The first two make a shop look broken. The last is
worse than broken: a photograph of another company's product on your own listing
is misleading to a shopper and trades on someone else's mark.

Commons is a general-purpose media archive, not a product-photography library.
Its search matches file descriptions, so "sandal" reaches a hiking photo whose
caption mentions sandals. There is no filter that fixes this, because the
problem is the corpus rather than the query.

What is left in its place is ``seed_demo_catalogue.py``'s drawn silhouettes:
obviously placeholders, consistent, and carrying no licence obligation and no
one else's branding. The only real answer is the shop's own photography.

Kept because the rate-limiting and attribution handling are worth having if a
properly licensed product-image source ever becomes available, and because the
finding above is worth not rediscovering.


**These are samples for development, not catalogue imagery.** Every file this
downloads is someone else's photograph of someone else's product, carrying a
Creative Commons licence with real obligations -- attribution, and for
share-alike licences, terms that propagate. None of that is appropriate for a
live shop selling its own goods. They exist so the storefront can be judged with
real photographs in it, and they are meant to be replaced, product by product,
through the admin.

Attribution is written to ``sample_image_credits.md`` as the files are fetched,
because a credit nobody recorded is a credit nobody can honour later.

Wikimedia Commons rather than a stock-photo API: it needs no key, its licences
are stated per file in the API response rather than assumed, and it is the only
source reachable here that returns topically correct results. Random-photo
services were the alternative and a landscape on a "Stiletto Pump" card is worse
than the drawn silhouette it would replace.

Run after seed_demo_catalogue.py, from the backend root:

    python scripts/fetch_sample_images.py
"""

import os
import sys
import time
import urllib.parse
import urllib.request

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

API = "https://commons.wikimedia.org/w/api.php"
# Commons asks for a descriptive agent with contact information. Sending the
# default urllib one is how a script gets blocked for everybody.
AGENT = "MarvelCommerce-DevSeed/1.0 (development sample fetch; contact: operator)"

# Preference order. A file whose licence needs no attribution is a smaller
# obligation to carry, so those are used first where the search offers them.
LICENCE_RANK = {
    "cc0": 0, "public domain": 0, "pd": 0,
    "cc by 4.0": 1, "cc by 3.0": 1, "cc by 2.0": 1,
    "cc by-sa 4.0": 2, "cc by-sa 3.0": 2, "cc by-sa 2.0": 2,
}

# Category slug -> what to search Commons for.
QUERIES = {
    "sandals": "women sandal shoe",
    "slippers": "slipper shoe",
    "flats": "flat shoe women",
    "ballerinas": "ballet flat shoe",
    "heels": "high heel shoe",
    "sneakers": "sneaker shoe white",
    "espadrilles": "espadrille shoe",
    "handbags": "handbag leather",
    "crossbody": "crossbody bag",
    "shoulder": "shoulder bag leather",
    "beach-bags": "tote bag",
    "clutches": "clutch bag evening",
    "wallets": "wallet leather purse",
}

CREDITS = []


class RateLimited(Exception):
    """Commons asked us to stop. It is not a failure to retry around."""


# Commons rate-limits, and it is right to. A first run of this script made about
# a hundred requests in a few seconds and was refused for exactly that. These
# numbers keep it to a trickle; PAUSE dominates the runtime and that is fine,
# because the alternative is being a bad guest on a donated resource.
PAUSE = 3.0
BACKOFF = 20.0
GIVE_UP_AFTER = 3

_consecutive_429 = 0


def _get(url: str, *, binary: bool):
    """One request, with the courtesy pause built in.

    Raises RateLimited once Commons has refused GIVE_UP_AFTER times in a row.
    Treating a 429 as a transient error and retrying through it is precisely the
    behaviour their policy exists to stop.
    """
    global _consecutive_429

    if _consecutive_429 >= GIVE_UP_AFTER:
        raise RateLimited("Commons refused repeatedly; stopping")

    time.sleep(PAUSE)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            _consecutive_429 = 0
            return response.read() if binary else response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _consecutive_429 += 1
            print(f"    · rate limited ({_consecutive_429}/{GIVE_UP_AFTER}); "
                  f"waiting {BACKOFF:.0f}s")
            time.sleep(BACKOFF)
        raise


def _strip_markup(value: str) -> str:
    """Commons returns the artist as an HTML fragment; a credits file wants text."""
    import re

    text = re.sub(r"<[^>]+>", "", value or "")
    return " ".join(text.split())[:120]


def search(term: str, limit: int = 8) -> list[dict]:
    """Candidate files for one search term, best licence first."""
    import json

    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}",
        "gsrlimit": str(limit),
        "gsrnamespace": "6",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1000",
        "format": "json",
    })
    try:
        payload = json.loads(_get(f"{API}?{params}", binary=False))
    except Exception as exc:  # noqa: BLE001 - a search that fails is a skip
        print(f"    ! search failed for {term!r}: {exc}")
        return []

    pages = (payload.get("query") or {}).get("pages") or {}
    candidates = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl")
        if not url:
            continue
        meta = info.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName", {}).get("value") or "unknown").strip()
        candidates.append({
            "title": page.get("title", ""),
            "url": url,
            "licence": licence,
            "author": _strip_markup(meta.get("Artist", {}).get("value", "")),
            "source": info.get("descriptionurl", ""),
        })

    candidates.sort(key=lambda c: LICENCE_RANK.get(c["licence"].lower(), 9))
    return candidates


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


def products_in(category_slug: str) -> list[Product]:
    category = db.execute(
        select(Category).where(Category.slug == category_slug)
    ).scalar_one_or_none()
    if category is None:
        return []
    return list(
        db.execute(
            select(Product)
            .where(Product.category_id == category.id, Product.status == "active")
            .order_by(Product.id)
        ).scalars()
    )


def main() -> None:
    staff = actor()

    try:
        sweep(staff)
    except RateLimited as exc:
        # Not an error to report as a failure. Commons asked us to stop, we
        # stopped, and whatever was fetched before that is kept -- re-running
        # later picks up where this left off.
        print(f"\n! {exc}. Keeping what was fetched; re-run later to continue.")

    db.commit()
    run_pending(db)
    invalidate_taxonomy()
    cache.invalidate_namespace(cache.NS_PRODUCT)
    cache.invalidate_namespace(cache.NS_LISTING)

    write_credits()
    fetched = len({credit["product"] for credit in CREDITS})
    print(f"\nproducts given sample photography: {fetched}")
    print("credits written to scripts/sample_image_credits.md")
    print("These are SAMPLES. Replace them with your own photography before launch.")


def sweep(staff) -> None:
    for category_slug, term in QUERIES.items():
        products = products_in(category_slug)
        if not products:
            continue

        # Two photographs per product, so the card's hover swap still swaps.
        wanted = len(products) * 2
        candidates = search(term, limit=max(8, wanted + 4))
        if not candidates:
            continue

        print(f"\n{category_slug}: {len(products)} product(s), "
              f"{len(candidates)} candidate image(s)")

        index = 0
        for product in products:
            picked = []
            while len(picked) < 2 and index < len(candidates):
                candidate = candidates[index]
                index += 1
                try:
                    data = _get(candidate["url"], binary=True)
                except RateLimited:
                    raise
                except Exception as exc:  # noqa: BLE001
                    print(f"    ! download failed: {exc}")
                    continue
                if len(data) < 8_000:
                    # Commons occasionally returns a tiny icon for a bad thumb
                    # request; too small to be a product photograph.
                    continue
                picked.append((candidate, data))

            if not picked:
                continue

            for image in db.execute(
                select(ProductImage).where(ProductImage.product_id == product.id)
            ).scalars().all():
                db.delete(image)
            db.flush()

            for candidate, data in picked:
                try:
                    add_image(
                        db, staff, product.id,
                        data=data,
                        filename=f"{product.slug}.jpg",
                        alt_text=product.slug.replace("-", " "),
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"    ! rejected by the pipeline: {exc}")
                    continue
                CREDITS.append({
                    "product": product.slug,
                    **{k: candidate[k] for k in ("title", "licence", "author", "source")},
                })

            print(f"    + {product.slug} ({len(picked)} image(s))")


def write_credits() -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "sample_image_credits.md")
    lines = [
        "# Sample image credits",
        "",
        "Development samples fetched from Wikimedia Commons by",
        "`scripts/fetch_sample_images.py`. **Not catalogue imagery.** Each file below",
        "is someone else's photograph under a Creative Commons licence with real",
        "obligations, and none of them depict this shop's own products.",
        "",
        "Replace them, product by product, through the admin before launch. This file",
        "exists so the obligations can be honoured for as long as they are in use.",
        "",
        "| Product | File | Licence | Author | Source |",
        "|---|---|---|---|---|",
    ]
    for credit in CREDITS:
        lines.append(
            f"| `{credit['product']}` | {credit['title'].removeprefix('File:')} "
            f"| {credit['licence']} | {credit['author'] or '—'} "
            f"| {credit['source']} |"
        )
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    finally:
        db.close()
