"""Catalog reads and writes for the operator's back-office.

Deliberately not built on ``repositories.product``. The public listing answers
"what may a shopper and a crawler see" — it filters to ``status='active'`` with a
published translation for one locale, and it is cached. The operator needs the
opposite: everything regardless of status, no locale scoping, and no cache,
because they are looking for the work that is *not* finished yet.

Bending one function to serve both would mean a boolean parameter that silently
decides whether unpublished products leak onto the storefront. Two functions
cannot make that mistake.

Query count is constant regardless of page size — three statements: the page,
its translations, and the total. ``scripts/check_query_count.py`` enforces a
budget on the public listing for the same reason.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.product_images import ProductImage
from models.product_translations import ProductTranslation
from models.product_variants import ProductVariant
from models.products import Product


def list_products_for_admin(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    """Paged product listing for the back-office, drafts included.

    ``status`` filters to one lifecycle state; ``search`` matches the base title
    or slug. Both are optional — the default view is everything, newest first,
    which is what an operator wants after adding a product.
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    variant_count = (
        select(func.count())
        .select_from(ProductVariant)
        .where(ProductVariant.product_id == Product.id)
        .scalar_subquery()
    )
    image_count = (
        select(func.count())
        .select_from(ProductImage)
        .where(ProductImage.product_id == Product.id)
        .scalar_subquery()
    )

    stmt = select(Product, variant_count, image_count)
    count_stmt = select(func.count()).select_from(Product)

    if status:
        stmt = stmt.where(Product.status == status)
        count_stmt = count_stmt.where(Product.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        # Base title/slug only. The operator searches for what they typed when
        # creating the product; translated titles are found on the edit screen.
        condition = Product.title.ilike(pattern) | Product.slug.ilike(pattern)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    rows = db.execute(
        stmt.order_by(Product.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    products = [r[0] for r in rows]
    ids = [p.id for p in products]

    by_product: dict[int, list] = {pid: [] for pid in ids}
    if ids:
        for tr in db.execute(
            select(ProductTranslation).where(ProductTranslation.product_id.in_(ids))
        ).scalars():
            by_product[tr.product_id].append(
                {
                    "locale": tr.locale,
                    "is_published": tr.is_published,
                    "is_complete": tr.is_complete,
                }
            )

    return {
        "items": [
            {
                "id": p.id,
                "slug": p.slug,
                "title": p.title,
                "brand": p.brand,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "variant_count": vc,
                "image_count": ic,
                "translations": sorted(
                    by_product[p.id], key=lambda t: t["locale"]
                ),
            }
            for p, vc, ic in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": db.execute(count_stmt).scalar_one(),
    }
