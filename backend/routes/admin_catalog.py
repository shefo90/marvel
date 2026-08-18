"""Back-office catalog endpoints.

Not locale-scoped, unlike the public routes. The storefront takes its locale
from the URL because section 8A requires stable per-language URLs for crawlers;
the admin panel is a logged-in tool with one interface language, and a product's
Arabic and English content are edited side by side on the same screen rather
than on two different URLs.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.admin_catalog import (
    create_product,
    list_products_for_admin,
    upsert_translation,
)
from routes.admin_deps import staff_at_least
from schema.admin_catalog import (
    admin_product_create,
    admin_product_detail,
    admin_product_list_response,
    admin_translation_detail,
    admin_translation_upsert,
)
from services.role_access_level import LEVEL_CATALOG

router = APIRouter(prefix="/api/admin", tags=["admin-catalog"])


@router.get("/products", response_model=admin_product_list_response)
def admin_list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Filter to one lifecycle state"),
    search: str | None = Query(None, description="Match base title or slug"),
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Every product the operator owns, drafts included.

    The public ``GET /products`` deliberately hides anything not active and
    published. This is the view that shows the operator what is still unfinished,
    including which language is missing.
    """
    return list_products_for_admin(
        db, page=page, page_size=page_size, status=status, search=search
    )


@router.post(
    "/products",
    response_model=admin_product_detail,
    status_code=http_status.HTTP_201_CREATED,
)
def admin_create_product(
    payload: admin_product_create,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create a product in draft. Publishing is a separate, validated step."""
    product = create_product(db, actor, payload.model_dump(exclude_none=False))
    db.commit()
    db.refresh(product)
    return product


@router.put(
    "/products/{product_id}/translations/{locale}",
    response_model=admin_translation_detail,
)
def admin_upsert_translation(
    product_id: int,
    locale: str,
    payload: admin_translation_upsert,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create or replace one language's content for a product."""
    tr = upsert_translation(
        db, actor, product_id, locale,
        payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(tr)
    return tr
