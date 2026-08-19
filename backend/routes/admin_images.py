"""Back-office image endpoints.

Multipart in, JSON out. The uploaded bytes are read here and handed straight to
the repository — nothing in this layer inspects the file, because the only
trustworthy identification is a decode, and that lives in ``services/images.py``.

The declared content type and the filename are carried along for error messages
only. Both are strings the uploader chose.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi import status as http_status
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.admin_images import (
    add_image,
    delete_image,
    reorder_images,
    set_primary_image,
    upsert_image_alt,
)
from routes.admin_deps import staff_at_least
from schema.admin_catalog import (
    admin_image_alt_upsert,
    admin_image_order,
    admin_image_row,
    admin_image_translation_detail,
)
from services.role_access_level import LEVEL_CATALOG

router = APIRouter(prefix="/api/admin", tags=["admin-images"])


@router.post(
    "/products/{product_id}/images",
    response_model=admin_image_row,
    status_code=http_status.HTTP_201_CREATED,
)
async def admin_upload_image(
    product_id: int,
    file: UploadFile = File(...),
    alt_text: str = Form(...),
    variant_id: int | None = Form(None),
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Upload one image. Alt text is required, not optional.

    ``ck_product_images_alt_text_not_blank`` makes it required in the database;
    asking for it here is what turns that into a sentence instead of a 500.
    """
    image = add_image(
        db, actor, product_id,
        data=await file.read(),
        filename=file.filename or "",
        alt_text=alt_text,
        variant_id=variant_id,
    )
    db.commit()
    db.refresh(image)
    return image


@router.patch("/images/{image_id}/primary", response_model=admin_image_row)
def admin_set_primary_image(
    image_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Promote one image. Whatever held the slot is demoted in the same call."""
    image = set_primary_image(db, actor, image_id)
    db.commit()
    db.refresh(image)
    return image


@router.put("/products/{product_id}/images/order", response_model=list[admin_image_row])
def admin_reorder_images(
    product_id: int,
    payload: admin_image_order,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Renumber the whole set. The list must name every image exactly once."""
    images = reorder_images(
        db, actor, product_id, payload.image_ids, variant_id=payload.variant_id
    )
    db.commit()
    for image in images:
        db.refresh(image)
    return images


@router.delete("/images/{image_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def admin_delete_image(
    image_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Remove an image. Unlike a product, an image really is deleted — nothing
    references it, and a photograph nobody wants is not history."""
    delete_image(db, actor, image_id)
    db.commit()


@router.put(
    "/images/{image_id}/alt/{locale}", response_model=admin_image_translation_detail
)
def admin_upsert_image_alt(
    image_id: int,
    locale: str,
    payload: admin_image_alt_upsert,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Per-locale alt text. Without it the Arabic page ships English alt text to
    Arabic readers and to image search."""
    row = upsert_image_alt(
        db, actor, image_id, locale, payload.alt_text, payload.title_attr
    )
    db.commit()
    db.refresh(row)
    return row
