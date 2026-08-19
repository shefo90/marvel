"""Product imagery for the back-office.

The database already enforces the hard rules — at most one primary image per
product and per variant, positions unique within their owner, alt text NOT NULL
and not blank. This layer exists to turn each of those into something the
operator can read before it becomes an IntegrityError, and to keep the files on
the volume consistent with the rows in Postgres.

Files are content-addressed (``services/storage.py``), which has one consequence
worth stating: two rows can legitimately point at the same file. Deleting a row
therefore checks whether any other row still uses that URL before removing
anything from disk.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.locales import Locale
from models.product_images import ProductImage
from models.product_image_translations import ProductImageTranslation
from models.products import Product
from repositories.admin_catalog import _invalidate
from services.images import ImageRejected, derivatives, process_upload
from services.storage import image_key, storage


def _owned_images(db: Session, product_id: int, variant_id: int | None):
    """Rows sharing one position sequence: uq_product_images_position is
    (product_id, variant_id, position) with NULLS NOT DISTINCT, so a variant's
    images are numbered independently of the product's."""
    return (
        select(ProductImage)
        .where(
            ProductImage.product_id == product_id,
            ProductImage.variant_id.is_(None)
            if variant_id is None
            else ProductImage.variant_id == variant_id,
        )
        .order_by(ProductImage.position)
    )


def add_image(
    db: Session,
    actor,
    product_id: int,
    *,
    data: bytes,
    filename: str,
    alt_text: str,
    variant_id: int | None = None,
) -> ProductImage:
    """Validate, re-encode, store every derivative, then record the row.

    Files are written before the row is inserted. That order can leak an
    orphaned file if the insert then fails, which is the harmless direction: a
    row pointing at a file that does not exist would be a broken image on the
    storefront, while an unreferenced file is only bytes.
    """
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    alt = (alt_text or "").strip()
    if not alt:
        # ck_product_images_alt_text_not_blank. Alt text is required because an
        # indexable image without it is inaccessible and invisible to image
        # search -- section 8A -- so the refusal has to say that, not 500.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="alt text is required, and describes the image for readers and image search",
        )

    try:
        processed = process_upload(data, filename=filename)
    except ImageRejected as rejected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(rejected)
        ) from None

    sizes = derivatives(processed)
    urls = {
        name: storage.put(
            image_key(processed.digest, name, processed.extension), payload
        )
        for name, payload in sizes.items()
    }

    existing = list(db.execute(_owned_images(db, product_id, variant_id)).scalars())
    next_position = max((row.position for row in existing), default=-1) + 1

    image = ProductImage(
        product_id=product_id,
        variant_id=variant_id,
        url=urls["full"],
        alt_text=alt,
        width=processed.width,
        height=processed.height,
        # The first image of a set is the primary one: a product with images but
        # no primary has nothing for a listing to show.
        is_primary=not existing,
        position=next_position,
    )
    db.add(image)
    db.flush()
    db.refresh(image)
    _invalidate(db, product_id)
    return image


def set_primary_image(db: Session, actor, image_id: int) -> ProductImage:
    """Promote one image, demoting whatever held the slot.

    uq_product_images_primary_product is a partial unique index, so setting the
    new primary without clearing the old one is an IntegrityError rather than a
    second primary. The clear is flushed first for the same reason.
    """
    image = db.get(ProductImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")

    for sibling in db.execute(
        _owned_images(db, image.product_id, image.variant_id)
    ).scalars():
        if sibling.id != image.id and sibling.is_primary:
            sibling.is_primary = False
    db.flush()

    image.is_primary = True
    db.flush()
    _invalidate(db, image.product_id)
    return image


def reorder_images(db: Session, actor, product_id: int, ordered_ids: list[int],
                   variant_id: int | None = None) -> list[ProductImage]:
    """Renumber a whole set in one go.

    Two passes, and it has to be two: uq_product_images_position is not
    deferrable, so writing final positions one row at a time collides the moment
    a row takes a position another row still holds. The first pass parks every
    row on a negative position, which nothing else can occupy.
    """
    images = list(db.execute(_owned_images(db, product_id, variant_id)).scalars())
    by_id = {image.id: image for image in images}

    if set(ordered_ids) != set(by_id) or len(ordered_ids) != len(images):
        # A partial list would leave the omitted rows holding positions that now
        # collide with the ones just written.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the new order must list every image exactly once",
        )

    for index, image_id in enumerate(ordered_ids):
        by_id[image_id].position = -(index + 1)
    db.flush()

    for index, image_id in enumerate(ordered_ids):
        by_id[image_id].position = index
    db.flush()

    _invalidate(db, product_id)
    return [by_id[image_id] for image_id in ordered_ids]


def delete_image(db: Session, actor, image_id: int) -> None:
    """Remove the row, then the files it alone was using.

    Images are the one thing here that *is* deleted rather than archived: unlike
    a product, nothing references an image row, and a photograph nobody wants is
    not history worth keeping.
    """
    image = db.get(ProductImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")

    product_id, variant_id = image.product_id, image.variant_id
    was_primary = image.is_primary
    url = image.url

    db.delete(image)
    db.flush()

    still_used = db.execute(
        select(func.count()).select_from(ProductImage).where(ProductImage.url == url)
    ).scalar_one()
    if still_used == 0:
        # Content-addressed keys mean the same photograph on two products is one
        # file on disk. Only the last row to leave takes the file with it.
        key = url.removeprefix(storage.url_prefix + "/")
        stem, _, tail = key.rpartition("-")
        extension = tail.split(".")[-1]
        for size in ("thumb", "card", "full"):
            storage.delete(f"{stem}-{size}.{extension}")

    if was_primary:
        # Otherwise the product keeps its images but loses the one a listing
        # shows. The next in order takes over.
        remaining = db.execute(_owned_images(db, product_id, variant_id)).scalars().first()
        if remaining is not None:
            remaining.is_primary = True
            db.flush()

    _invalidate(db, product_id)


def upsert_image_alt(
    db: Session, actor, image_id: int, locale: str, alt_text: str,
    title_attr: str | None = None,
) -> ProductImageTranslation:
    """Per-locale alt text.

    The base ``alt_text`` column is English. Without this the Arabic page ships
    English alt text to Arabic readers and to image search, which section 8A
    treats as a defect rather than a nicety.
    """
    image = db.get(ProductImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")
    if db.get(Locale, locale) is None:
        raise HTTPException(status_code=400, detail=f"unknown locale {locale}")

    alt = (alt_text or "").strip()
    if not alt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="alt text is required",
        )

    row = db.execute(
        select(ProductImageTranslation).where(
            ProductImageTranslation.product_image_id == image_id,
            ProductImageTranslation.locale == locale,
        )
    ).scalar_one_or_none()

    if row is None:
        row = ProductImageTranslation(
            product_image_id=image_id, locale=locale, alt_text=alt,
            title_attr=title_attr,
        )
        db.add(row)
    else:
        row.alt_text = alt
        if title_attr is not None:
            row.title_attr = title_attr

    db.flush()
    _invalidate(db, image.product_id)
    return row
