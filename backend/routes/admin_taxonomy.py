"""Back-office endpoints for the category tree and the collections.

No delete anywhere. A category has products pointing at it and a collection has
an ``item_list_id`` already stamped onto historic cart and order lines, so
removing either would break attribution that section 5 exists to preserve.
``is_active`` is the operator's switch, as it is for promotions.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, Path
from fastapi import status as http_status
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.admin_taxonomy import (
    collection_product_ids,
    create_category,
    create_collection,
    list_category_tree_for_admin,
    list_collections_for_admin,
    set_collection_products,
    update_category,
    update_collection,
    upsert_category_translation,
    upsert_collection_translation,
)
from routes.admin_deps import staff_at_least
from schema.admin_taxonomy import (
    admin_category_create,
    admin_category_node,
    admin_category_update,
    admin_collection_create,
    admin_collection_members,
    admin_collection_row,
    admin_collection_update,
    admin_translation_upsert,
)
from services.role_access_level import LEVEL_CATALOG

router = APIRouter(prefix="/api/admin", tags=["admin-taxonomy"])

LOCALE = Path(..., min_length=2, max_length=5)


@router.get("/taxonomy/categories", response_model=list[admin_category_node])
def admin_category_tree(
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """The whole tree, inactive rows included and flagged.

    Inactive is shown rather than hidden: the operator is the one who
    deactivated it, and a category that vanishes from its own editor reads as
    deleted.
    """
    return list_category_tree_for_admin(db)


@router.post(
    "/taxonomy/categories",
    response_model=admin_category_node,
    status_code=http_status.HTTP_201_CREATED,
)
def admin_create_category(
    payload: admin_category_create,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create a category. Omit ``parent_id`` for a top-level one.

    The level is derived from the parent, never sent — see the schema.
    """
    category = create_category(db, actor, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(category)
    return category


@router.patch(
    "/taxonomy/categories/{category_id}", response_model=admin_category_node
)
def admin_update_category(
    category_id: int,
    payload: admin_category_update,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    category = update_category(
        db, actor, category_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(category)
    return category


@router.put("/taxonomy/categories/{category_id}/translations/{locale}")
def admin_upsert_category_translation(
    category_id: int,
    payload: admin_translation_upsert,
    locale: str = LOCALE,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """One language's name, slug and SEO copy.

    The storefront resolves a category URL through this row, so a category with
    no translation in a locale is simply absent from that language's menu.
    """
    tr = upsert_category_translation(
        db, actor, category_id, locale, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(tr)
    return {
        "locale": tr.locale, "title": tr.title, "slug": tr.slug,
        "description": tr.description, "meta_description": tr.meta_description,
        "is_published": tr.is_published,
    }


@router.get("/taxonomy/collections", response_model=list[admin_collection_row])
def admin_list_collections(
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Curated edits. Flat by nature — a collection cuts across the tree."""
    return list_collections_for_admin(db)


@router.post(
    "/taxonomy/collections",
    response_model=admin_collection_row,
    status_code=http_status.HTTP_201_CREATED,
)
def admin_create_collection(
    payload: admin_collection_create,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    collection = create_collection(db, actor, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(collection)
    return collection


@router.patch(
    "/taxonomy/collections/{collection_id}", response_model=admin_collection_row
)
def admin_update_collection(
    collection_id: int,
    payload: admin_collection_update,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    collection = update_collection(
        db, actor, collection_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(collection)
    return collection


@router.put("/taxonomy/collections/{collection_id}/translations/{locale}")
def admin_upsert_collection_translation(
    collection_id: int,
    payload: admin_translation_upsert,
    locale: str = LOCALE,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    tr = upsert_collection_translation(
        db, actor, collection_id, locale, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(tr)
    return {
        "locale": tr.locale, "title": tr.title, "slug": tr.slug,
        "description": tr.description, "meta_description": tr.meta_description,
        "is_published": tr.is_published,
    }


@router.get("/taxonomy/collections/{collection_id}/products")
def admin_get_collection_products(
    collection_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    return {"product_ids": collection_product_ids(db, collection_id)}


@router.put("/taxonomy/collections/{collection_id}/products")
def admin_set_collection_products(
    collection_id: int,
    payload: admin_collection_members,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Replace the membership in one call, in the order given.

    The order is the data: it drives section 5's ``index`` and the collection's
    own "featured" sort, so a partial add/remove endpoint could not express a
    reordering.
    """
    ordered = set_collection_products(db, actor, collection_id, payload.product_ids)
    db.commit()
    return {"product_ids": ordered}
