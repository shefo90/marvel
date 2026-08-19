"""Public catalog endpoints — section 14's ``GET /products``, ``/products/{slug}``.

No SQLAlchemy in this layer. The locale is a path segment rather than a header
or a cookie, because section 8A requires stable locale URLs and forbids
resolving language by IP — the URL must be the only thing that decides which
language a crawler or a user gets.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from models.locales import Locale
from repositories.product import get_product_by_slug, list_products
from repositories.taxonomy import (
    category_tree,
    get_category,
    get_collection,
    list_collections,
)
from schema.product import product_list_response, product_response
from schema.taxonomy import category_detail, category_node, collection_node
from services import cache

router = APIRouter(prefix="/api/{locale}", tags=["catalog"])


def valid_locale(
    locale: str = Path(..., min_length=2, max_length=5),
    db: Session = Depends(get_db),
) -> str:
    """Reject unknown locale segments outright.

    Section 8A: "/ar-eg/, /AR/, /arabic/ return 404 unless present in an
    explicit alias map." Rendering content at HTTP 200 under an unrecognised
    locale is exactly the soft-404 behaviour the spec forbids.
    """
    row = db.execute(
        select(Locale).where(Locale.code == locale, Locale.is_active.is_(True))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown locale")
    return locale


@router.get("/products", response_model=product_list_response)
def list_catalog(
    response: Response,
    locale: str = Depends(valid_locale),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    category: str | None = Query(None),
    collection: str | None = Query(None),
    # Repeatable, so ?size=38&size=39 reads as "either". Codes, never labels:
    # the Arabic page must send "black", not the word it displays.
    size: list[str] = Query(default_factory=list),
    color: list[str] = Query(default_factory=list),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    in_stock: bool = Query(False),
    sort: str = Query("featured", pattern="^(featured|newest|price_asc|price_desc)$"),
    db: Session = Depends(get_db),
):
    # Short and revalidatable: this payload carries price and stock, and a stale
    # price is the "price mismatch" defect section 8 tells us to monitor for.
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=30"
    return list_products(
        db,
        locale=locale,
        page=page,
        page_size=page_size,
        category_slug=category,
        collection_slug=collection,
        sizes=size,
        colors=color,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        sort=sort,
    )


@router.get("/categories", response_model=list[category_node])
def list_category_tree(
    response: Response,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """The navigation menu. Always exactly two levels deep — see the taxonomy
    repository; the database makes a third level unrepresentable."""
    # Longer than a listing: this carries no price and no stock, only names the
    # operator edits.
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=60"
    return category_tree(db, locale)


@router.get("/categories/{slug}", response_model=category_detail)
def get_category_page(
    response: Response,
    slug: str,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """A category's own copy and SEO fields, plus its parent for the breadcrumb.

    Separate from the listing on purpose: the products change with every filter
    the shopper ticks, the category heading does not, and merging them would
    make the page's own title uncacheable.
    """
    category = get_category(db, locale, slug)
    if category is None:
        raise HTTPException(status_code=404, detail="unknown category")
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=60"
    return category


@router.get("/collections", response_model=list[collection_node])
def list_all_collections(
    response: Response,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Curated edits. Flat, never nested — a collection cuts across categories."""
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=60"
    return list_collections(db, locale)


@router.get("/collections/{slug}", response_model=collection_node)
def get_collection_page(
    response: Response,
    slug: str,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    collection = get_collection(db, locale, slug)
    if collection is None:
        raise HTTPException(status_code=404, detail="unknown collection")
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=60"
    return collection


@router.get("/products/{slug}", response_model=product_response)
def get_catalog_product(
    response: Response,
    slug: str,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    product = get_product_by_slug(db, locale=locale, slug=slug)
    if product is None:
        # A real 404, not a branded page at HTTP 200 (section 8A soft-404 rule).
        # Note this is also what an unpublished translation returns: falling
        # back to the other language would make the hreflang cluster claim a
        # translation that does not exist.
        raise HTTPException(status_code=404, detail="product not found")

    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=30"
    return product
