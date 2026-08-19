"""Category reads for the back-office.

Deliberately not part of ``repositories.admin_catalog`` — that file already
carries two responsibilities and was flagged for splitting, and this shares none
of its concerns. Categories are read-only here: the operator picks one, and
nothing in stage 1 creates or edits the taxonomy.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from models.categories import Category


def list_categories_for_admin(db: Session) -> list[dict]:
    """Every level-2 category with its parent's name, for the product picker.

    Level 2 only. ``products.category_level`` is generated as 2 with a composite
    FK to ``categories(id, level)``, so ``create_product`` refuses a level-1
    category with a 400 — a picker offering one would be offering an error.

    Inactive categories are returned and flagged rather than hidden: a product
    may already sit in one that was since deactivated, and omitting it would
    render that product as having no category at all. Hiding a choice the
    operator can already see the consequences of is worse than showing it
    greyed.

    One query. The parent name is joined rather than lazy-loaded per row, which
    is the same reason ``list_products_for_admin`` builds its counts as scalar
    subqueries: the shape must stay constant as the taxonomy grows.
    """
    parent = aliased(Category)
    rows = db.execute(
        select(Category, parent.name)
        .join(parent, Category.parent_id == parent.id)
        .where(Category.level == 2)
        .order_by(parent.name, Category.position, Category.name)
    ).all()

    return [
        {
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
            "parent_id": category.parent_id,
            "parent_name": parent_name,
            "position": category.position,
            "is_active": category.is_active,
        }
        for category, parent_name in rows
    ]
