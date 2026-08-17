"""Back-office catalog endpoints.

Not locale-scoped, unlike the public routes. The storefront takes its locale
from the URL because section 8A requires stable per-language URLs for crawlers;
the admin panel is a logged-in tool with one interface language, and a product's
Arabic and English content are edited side by side on the same screen rather
than on two different URLs.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.admin_catalog import list_products_for_admin
from routes.admin_deps import staff_at_least
from schema.admin_catalog import admin_product_list_response
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
