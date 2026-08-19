"""Back-office endpoints for offers.

No delete. ``is_active`` is the operator's switch, and a promotion that priced
real orders is history those orders point at — ``order_items.promotion_id`` is
ON DELETE SET NULL precisely so a removed campaign cannot take an order's
attribution with it, but the right answer is not to remove it.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends
from fastapi import status as http_status
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.admin_promotions import (
    create_promotion,
    list_promotions,
    promotion_detail,
    set_targets,
    update_promotion,
)
from routes.admin_deps import staff_at_least
from schema.admin_catalog import (
    admin_promotion_create,
    admin_promotion_row,
    admin_promotion_target,
    admin_promotion_update,
)
from services.role_access_level import LEVEL_CATALOG

router = APIRouter(prefix="/api/admin", tags=["admin-promotions"])


@router.get("/promotions", response_model=list[admin_promotion_row])
def admin_list_promotions(
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Every offer, newest first — usually what the operator just made."""
    return list_promotions(db)


@router.post(
    "/promotions",
    response_model=admin_promotion_row,
    status_code=http_status.HTTP_201_CREATED,
)
def admin_create_promotion(
    payload: admin_promotion_create,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Create an offer and say what it applies to, in one call.

    One call because the two halves are not independently useful: a promotion
    without targets discounts nothing, so saving it alone would create a row
    that looks live and does nothing.
    """
    promotion = create_promotion(db, actor, payload.model_dump())
    db.commit()
    return promotion_detail(db, promotion.id)


@router.get("/promotions/{promotion_id}", response_model=admin_promotion_row)
def admin_get_promotion(
    promotion_id: int,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    return promotion_detail(db, promotion_id)


@router.patch("/promotions/{promotion_id}", response_model=admin_promotion_row)
def admin_update_promotion(
    promotion_id: int,
    payload: admin_promotion_update,
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Edit an offer. Pausing it is ``is_active``, and needs no date change."""
    update_promotion(db, actor, promotion_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return promotion_detail(db, promotion_id)


@router.put("/promotions/{promotion_id}/targets", response_model=admin_promotion_row)
def admin_set_promotion_targets(
    promotion_id: int,
    payload: list[admin_promotion_target],
    actor: User = Depends(staff_at_least(LEVEL_CATALOG)),
    db: Session = Depends(get_db),
):
    """Replace what the offer applies to. The list sent is the list kept."""
    set_targets(db, actor, promotion_id, [target.model_dump() for target in payload])
    db.commit()
    return promotion_detail(db, promotion_id)
