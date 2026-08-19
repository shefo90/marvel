"""Back-office order endpoints.

Gated at ``operations`` (3), not ``catalog`` (2): the person who writes product
descriptions is not automatically the person who moves someone's order to
shipped. The ladder has reserved this level since S1 for exactly this.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.enums import OrderStatus
from core.db import get_db
from models.users import User
from repositories.admin_orders import (
    get_order_for_admin,
    list_orders_for_admin,
    update_order_status,
)
from routes.admin_deps import staff_at_least
from schema.admin_orders import (
    admin_order_detail,
    admin_order_list_response,
    admin_order_status_update,
)
from services.role_access_level import LEVEL_OPERATIONS

router = APIRouter(prefix="/api/admin", tags=["admin-orders"])


@router.get("/orders", response_model=admin_order_list_response)
def admin_list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: OrderStatus | None = Query(None, description="Filter to one lifecycle state"),
    search: str | None = Query(None, description="Order number or customer email"),
    actor: User = Depends(staff_at_least(LEVEL_OPERATIONS)),
    db: Session = Depends(get_db),
):
    """The work queue, newest first — what just came in."""
    return list_orders_for_admin(
        db, page=page, page_size=page_size,
        status=status.value if status else None, search=search,
    )


@router.get("/orders/{order_number}", response_model=admin_order_detail)
def admin_get_order(
    order_number: str,
    actor: User = Depends(staff_at_least(LEVEL_OPERATIONS)),
    db: Session = Depends(get_db),
):
    """One order: its money, its lines, and every status move it has made.

    Addressed by order number rather than id — it is the immutable commerce
    identity and the thing a shopper quotes on the phone.
    """
    return get_order_for_admin(db, order_number)


@router.patch("/orders/{order_number}/status", response_model=admin_order_detail)
def admin_update_order_status(
    order_number: str,
    payload: admin_order_status_update,
    actor: User = Depends(staff_at_least(LEVEL_OPERATIONS)),
    db: Session = Depends(get_db),
):
    """Advance an order, and record who advanced it.

    Impossible moves are refused with 409: a delivered order cannot return to
    pending, and writing that down would put a sequence in the history that
    never happened.
    """
    update_order_status(db, actor, order_number, payload.status.value, payload.reason)
    db.commit()
    return get_order_for_admin(db, order_number)
