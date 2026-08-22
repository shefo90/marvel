"""Queries and writes for the signed-in shopper.

Every function takes ``customer_id`` as its first real argument and filters on
it. That is not defensive style, it is the authorisation model: there is no
separate permission check anywhere above this layer, so a query here that
forgets its ``customer_id`` predicate is a query that shows one shopper another
shopper's orders. Passing the id rather than reading it from a global is what
makes forgetting it visible in the function signature.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.addresses import Address
from models.order_items import OrderItem
from models.orders import Order


def list_customer_orders(db: Session, customer_id: int) -> list[dict]:
    """This shopper's orders, newest first.

    The item count comes from a grouped subquery rather than from loading the
    lines: an order history page shows "3 items", and fetching every line of
    every order to count them would be the whole catalogue for a frequent
    shopper.
    """
    counts = (
        select(OrderItem.order_id, func.sum(OrderItem.quantity).label("item_count"))
        .group_by(OrderItem.order_id)
        .subquery()
    )

    rows = db.execute(
        select(Order, func.coalesce(counts.c.item_count, 0))
        .outerjoin(counts, counts.c.order_id == Order.id)
        .where(Order.customer_id == customer_id)
        .order_by(Order.placed_at.desc().nullslast(), Order.id.desc())
    ).all()

    return [_row(order, item_count) for order, item_count in rows]


def read_customer_order(db: Session, customer_id: int, order_number: str) -> dict:
    """One order with its lines, if it belongs to this shopper.

    Somebody else's order is a 404, not a 403. Order numbers are short and
    prefixed, so a 403 would confirm which guesses were real -- and "this exists
    but is not yours" is information the guesser did not have.
    """
    order = db.execute(
        select(Order).where(
            Order.customer_id == customer_id, Order.order_number == order_number
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")

    items = db.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.line_number)
    ).scalars().all()

    payload = _row(order, sum(item.quantity for item in items))
    payload.update({
        "subtotal": order.subtotal,
        "discount": order.discount,
        "shipping": order.shipping,
        "tax_total": order.tax_total,
        "coupon_code": order.coupon_code,
        "items": [
            {
                "sku": item.sku,
                "product_title": item.product_title,
                "variant_label": item.variant_label,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
            }
            for item in items
        ],
    })
    return payload


def _row(order: Order, item_count: int) -> dict:
    """The shopper-visible half of an order.

    Listed explicitly rather than handed the model, so that the margin columns
    section 11A adds to this table -- cogs, contribution profit, gateway fees --
    cannot reach a customer-facing response by being added to the schema.
    """
    return {
        "order_number": order.order_number,
        "status": _value(order.status),
        "payment_status": _value(order.payment_status),
        "payment_method": _value(order.payment_method),
        "currency": order.currency,
        "total": order.total,
        "placed_at": order.placed_at,
        "business_date": order.business_date,
        "item_count": int(item_count or 0),
    }


def _value(value):
    return getattr(value, "value", value)


# --- addresses -----------------------------------------------------------

def list_addresses(db: Session, customer_id: int) -> list[Address]:
    """The shopper's live addresses. Archived ones stay out of the book."""
    return list(
        db.execute(
            select(Address)
            .where(Address.customer_id == customer_id, Address.archived_at.is_(None))
            .order_by(Address.is_default_shipping.desc(), Address.id)
        ).scalars()
    )


def _owned(db: Session, customer_id: int, address_id: int) -> Address:
    address = db.execute(
        select(Address).where(
            Address.id == address_id,
            Address.customer_id == customer_id,
            Address.archived_at.is_(None),
        )
    ).scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=404, detail="address not found")
    return address


def _clear_other_defaults(db: Session, customer_id: int, keep_id: int | None) -> None:
    """Demote every other default, and flush before the caller promotes.

    ``uq_addresses_default_shipping`` is a partial unique index on
    ``customer_id WHERE is_default_shipping AND archived_at IS NULL``, so the
    database already guarantees at most one. That makes the *order* of these two
    writes load-bearing rather than cosmetic: promote first and the UPDATE
    collides with the row still holding the flag, which surfaces as a raw
    IntegrityError on a request the shopper thinks is a checkbox.

    The flush is the point of this function. Demoting in the ORM without
    flushing leaves the promotion free to autoflush first, in whatever order the
    unit of work chooses -- which is exactly how this failed the first time.
    """
    others = db.execute(
        select(Address).where(
            Address.customer_id == customer_id,
            Address.is_default_shipping.is_(True),
            Address.archived_at.is_(None),
            Address.id != keep_id if keep_id is not None else True,
        )
    ).scalars().all()

    if not others:
        return
    for other in others:
        other.is_default_shipping = False
    db.flush()


def create_address(db: Session, customer_id: int, payload: dict) -> Address:
    address = Address(customer_id=customer_id, **payload)

    # The first address a shopper saves is their default, whatever they ticked.
    # An address book whose only entry is not the default makes checkout ask a
    # question with one possible answer.
    if not list_addresses(db, customer_id):
        address.is_default_shipping = True

    # Before the row is added, so the demotion reaches the database first.
    if address.is_default_shipping:
        _clear_other_defaults(db, customer_id, None)

    db.add(address)
    db.flush()
    return address


def update_address(
    db: Session, customer_id: int, address_id: int, payload: dict
) -> Address:
    address = _owned(db, customer_id, address_id)

    # Demote first, then apply. Assigning is_default_shipping before the other
    # rows have been cleared lets autoflush emit the promotion into a state the
    # unique index still forbids.
    if payload.get("is_default_shipping"):
        _clear_other_defaults(db, customer_id, address.id)

    for field, value in payload.items():
        setattr(address, field, value)

    db.flush()
    return address


def archive_address(db: Session, customer_id: int, address_id: int) -> None:
    """Archive rather than delete.

    ``order_addresses`` snapshots the delivery address onto the order, so no
    historic order is damaged either way -- but nothing else in this schema
    destroys a customer record, and ``archived_at`` exists to say so.

    Archiving the default promotes the oldest survivor. Leaving a shopper with
    addresses but no default would make checkout preselect nothing, which reads
    as the address book having lost them.
    """
    address = _owned(db, customer_id, address_id)
    was_default = address.is_default_shipping

    address.is_default_shipping = False
    address.archived_at = func.now()
    db.flush()

    if was_default:
        remaining = list_addresses(db, customer_id)
        if remaining:
            remaining[0].is_default_shipping = True
            db.flush()
