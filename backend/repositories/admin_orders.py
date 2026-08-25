"""Order management for the back-office.

The `operations` rung of the role ladder, reserved since S1 and until now
unused: the storefront places orders and nothing could see them.

**Status changes are recorded, not merely applied.** Every move writes an
``order_status_history`` row, because a status column answers "what is it now"
and an operator needs "who moved it, when, and why".

**A status change is not a money change.** Nothing here touches ``total``,
``subtotal`` or ``discount``. Those are watched by the migration-0004 audit
trigger and belong to refunds, which arrive with S4 — a status screen that
could edit a total would be a way to move money without an audit row.
"""

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.enums import ActorType, CodCollectionStatus, OrderStatus
from models.customers import Customer
from models.order_items import OrderItem
from models.order_status_history import OrderStatusHistory
from models.orders import Order

_STATUSES = {s.value for s in OrderStatus}

# Which moves are real. Not every pair: a delivered order cannot become pending
# again, and recording one would put a sequence in the history that never
# happened -- every funnel built on that history would then be wrong.
_ALLOWED: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered", "returned", "cancelled"},
    "delivered": {"returned"},
    # Terminal. A cancelled or returned order is closed; anything further is a
    # new order or a refund, not a status edit.
    "cancelled": set(),
    "returned": set(),
}


def _enum(value):
    return value.value if hasattr(value, "value") else value


def _money(value):
    return str(value) if value is not None else None


def list_orders_for_admin(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    """The queue an operator works from, newest first.

    Newest first because this screen is opened to see what just came in, not to
    browse history.
    """
    if status is not None and status not in _STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{status} is not an order status",
        )

    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    stmt = select(Order, Customer).join(Customer, Customer.id == Order.customer_id, isouter=True)
    count_stmt = select(func.count()).select_from(Order)

    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
    if search:
        # The order number is what a shopper quotes on the phone, so it is the
        # search. Email is included because it is the other thing they know.
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Order.order_number.ilike(pattern), Customer.email.ilike(pattern))
        )
        count_stmt = count_stmt.join(
            Customer, Customer.id == Order.customer_id, isouter=True
        ).where(or_(Order.order_number.ilike(pattern), Customer.email.ilike(pattern)))

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(Order.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return {
        "items": [
            {
                "order_number": order.order_number,
                "status": _enum(order.status),
                "payment_status": _enum(order.payment_status),
                "payment_method": _enum(order.payment_method),
                "cod_collection_status": _enum(order.cod_collection_status),
                "total": _money(order.total),
                "currency": order.currency,
                "locale": order.locale,
                "customer_email": customer.email if customer else None,
                "placed_at": order.placed_at,
            }
            for order, customer in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _load(db: Session, order_number: str) -> Order:
    order = db.execute(
        select(Order).where(Order.order_number == order_number)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


def get_order_for_admin(db: Session, order_number: str) -> dict:
    """Everything about one order: its money, its lines, and its history."""
    order = _load(db, order_number)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None

    items = [
        {
            "line_number": item.line_number,
            "sku": item.sku,
            "product_title": item.product_title,
            "variant_label": item.variant_label,
            "quantity": item.quantity,
            "unit_list_price": _money(item.unit_list_price),
            "unit_price": _money(item.unit_price),
            "discount_amount": _money(item.discount_amount),
            "discount_source": _enum(item.discount_source),
            "line_total": _money(item.line_total),
            "refunded_quantity": item.refunded_quantity,
        }
        for item in db.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.line_number)
        ).scalars()
    ]

    history = [
        {
            "dimension": entry.dimension,
            "from_status": entry.from_status,
            "to_status": entry.to_status,
            "actor_type": _enum(entry.actor_type),
            "actor_user_id": entry.actor_user_id,
            "reason": entry.reason,
            "created_at": entry.created_at,
        }
        for entry in db.execute(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order.id)
            .order_by(OrderStatusHistory.id)
        ).scalars()
    ]

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": _enum(order.status),
        "payment_status": _enum(order.payment_status),
        "payment_method": _enum(order.payment_method),
        "cod_collection_status": _enum(order.cod_collection_status),
        "locale": order.locale,
        "currency": order.currency,
        "subtotal": _money(order.subtotal),
        "discount": _money(order.discount),
        "shipping": _money(order.shipping),
        "tax_total": _money(order.tax_total),
        "total": _money(order.total),
        "promotion_cost_total": _money(order.promotion_cost_total),
        "refunded_amount_total": _money(order.refunded_amount_total),
        "customer_email": customer.email if customer else None,
        "customer_phone": customer.phone if customer else None,
        "placed_at": order.placed_at,
        "items": items,
        "status_history": history,
    }


def update_order_status(
    db: Session, actor, order_number: str, to_status: str, reason: str | None = None
) -> Order:
    """Move one order along, and write down that it moved."""
    if to_status not in _STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{to_status} is not an order status",
        )

    order = _load(db, order_number)
    current = _enum(order.status)

    # Two operators clicking the same button must not write two history rows
    # describing a transition that did not happen.
    if current == to_status:
        return order

    if to_status not in _ALLOWED.get(current, set()):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"an order cannot go from {current} to {to_status}",
        )

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            dimension="order",
            from_status=current,
            to_status=to_status,
            actor_type=ActorType.staff,
            actor_user_id=actor.id if actor is not None else None,
            source="admin",
            reason=reason,
        )
    )
    order.status = to_status

    # The courier hands over the cash at delivery. Leaving this at 'pending'
    # would mean the books say nobody paid for an order already in the
    # customer's hands.
    if (
        to_status == OrderStatus.delivered.value
        and order.cod_collection_status is not None
        and _enum(order.cod_collection_status) == CodCollectionStatus.pending.value
    ):
        order.cod_collection_status = CodCollectionStatus.collected.value

    db.flush()
    db.refresh(order)
    return order
