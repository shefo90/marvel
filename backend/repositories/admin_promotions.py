"""Creating and editing offers.

Every validation here mirrors a CHECK constraint that would otherwise fire as an
IntegrityError. That is worth more on this table than on most: these rows price
real baskets, so a half-specified promotion is not a validation nicety — it is a
wrong number on somebody's order, discovered by a shopper rather than by us.

Two rules are enforced here that the database cannot express:

* **at least one target**, because a promotion with none applies to nothing and
  fails silently — the database is right to allow it (targets are added after
  the row exists) but an operator never means it
* **the target must exist**, because a target pointing at a deleted product
  matches nothing, which is the same silent failure wearing a different hat
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.categories import Category
from models.collections import Collection
from models.product_variants import ProductVariant
from models.products import Product
from models.promotion_targets import PromotionTarget
from models.promotions import Promotion

_TARGET_MODELS = {
    "product": Product,
    "variant": ProductVariant,
    "category": Category,
    "collection": Collection,
}

_EDITABLE = (
    "name", "discount_percent", "discount_amount", "buy_quantity",
    "get_quantity", "get_discount_percent", "starts_at", "ends_at", "is_active",
)


def _reject(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
    )


def _decimal(value, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _reject(f"{field} is not a number")


def _validate_shape(values: dict) -> None:
    """Mirror ck_promotions_*_shape, in the order an operator would read it."""
    kind = values.get("type")
    percent = _decimal(values.get("discount_percent"), "discount percent")
    amount = _decimal(values.get("discount_amount"), "discount amount")

    if kind == "percentage":
        if percent is None:
            _reject("a percentage promotion needs a discount percent")
        if not (Decimal("0") < percent <= Decimal("100")):
            _reject("the discount percent must be above 0 and at most 100")
        if amount is not None:
            _reject("a percentage promotion cannot also carry a fixed amount")
        if values.get("buy_quantity") or values.get("get_quantity"):
            _reject("a percentage promotion cannot carry BOGO quantities")

    elif kind == "fixed":
        if amount is None:
            _reject("a fixed promotion needs a discount amount")
        if amount <= 0:
            _reject("the discount amount must be above 0")
        if percent is not None:
            _reject("a fixed promotion cannot also carry a percentage")
        if values.get("buy_quantity") or values.get("get_quantity"):
            _reject("a fixed promotion cannot carry BOGO quantities")

    elif kind == "bogo":
        buy, get = values.get("buy_quantity"), values.get("get_quantity")
        get_percent = _decimal(values.get("get_discount_percent"), "get discount percent")
        if not buy or not get or get_percent is None:
            _reject(
                "a BOGO promotion needs a buy quantity, a get quantity and a "
                "discount on the free units"
            )
        if buy <= 0 or get <= 0:
            _reject("the BOGO quantities must be above 0")
        if not (Decimal("0") < get_percent <= Decimal("100")):
            _reject("the BOGO discount must be above 0 and at most 100 percent")
        if percent is not None or amount is not None:
            _reject("a BOGO promotion carries quantities, not a percentage or an amount")

    else:
        _reject("type must be percentage, fixed or bogo")

    starts_at: datetime | None = values.get("starts_at")
    ends_at: datetime | None = values.get("ends_at")
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        # Such a promotion is never live: a silent no-op rather than an error
        # the operator would ever notice.
        _reject("the end of the window must be after its start")


def _validate_targets(db: Session, targets: list[dict]) -> None:
    if not targets:
        _reject(
            "choose what this applies to — a promotion with no targets discounts "
            "nothing. Pick 'all' to mean the whole catalogue."
        )

    seen = set()
    for target in targets:
        kind = target.get("target_type")
        target_id = target.get("target_id")

        if kind == "all":
            if target_id is not None:
                _reject("the 'all' target covers the whole catalogue and takes no id")
        elif kind in _TARGET_MODELS:
            if target_id is None:
                _reject(f"a {kind} target needs a {kind} to point at")
            if db.get(_TARGET_MODELS[kind], target_id) is None:
                # Otherwise the promotion is saved, matches nothing, and appears
                # to be running.
                _reject(f"no {kind} with id {target_id}")
        else:
            _reject(f"{kind} is not a target type")

        key = (kind, target_id)
        if key in seen:
            _reject("the same target is listed twice")
        seen.add(key)


def _write_targets(db: Session, promotion_id: int, targets: list[dict]) -> None:
    for existing in db.execute(
        select(PromotionTarget).where(PromotionTarget.promotion_id == promotion_id)
    ).scalars():
        db.delete(existing)
    db.flush()

    for target in targets:
        db.add(PromotionTarget(
            promotion_id=promotion_id,
            target_type=target["target_type"],
            target_id=target.get("target_id"),
        ))
    db.flush()


def create_promotion(db: Session, actor, payload: dict) -> Promotion:
    values = dict(payload)
    targets = values.pop("targets", [])
    _validate_shape(values)
    _validate_targets(db, targets)

    promotion = Promotion(
        name=values["name"],
        type=values["type"],
        discount_percent=values.get("discount_percent"),
        discount_amount=values.get("discount_amount"),
        buy_quantity=values.get("buy_quantity"),
        get_quantity=values.get("get_quantity"),
        get_discount_percent=values.get("get_discount_percent"),
        starts_at=values.get("starts_at"),
        ends_at=values.get("ends_at"),
        is_active=values.get("is_active", True),
        created_by_user_id=actor.id if actor is not None else None,
    )
    db.add(promotion)
    db.flush()

    _write_targets(db, promotion.id, targets)
    db.refresh(promotion)
    return promotion


def get_promotion(db: Session, promotion_id: int) -> Promotion:
    promotion = db.get(Promotion, promotion_id)
    if promotion is None:
        raise HTTPException(status_code=404, detail="promotion not found")
    return promotion


def update_promotion(db: Session, actor, promotion_id: int, payload: dict) -> Promotion:
    promotion = get_promotion(db, promotion_id)

    # The shape is checked against the row as it WOULD be, not against the patch
    # alone: clearing a percentage on a percentage promotion is only invalid in
    # the context of the type it keeps.
    merged = {
        "type": promotion.type.value if hasattr(promotion.type, "value") else promotion.type,
        "discount_percent": promotion.discount_percent,
        "discount_amount": promotion.discount_amount,
        "buy_quantity": promotion.buy_quantity,
        "get_quantity": promotion.get_quantity,
        "get_discount_percent": promotion.get_discount_percent,
        "starts_at": promotion.starts_at,
        "ends_at": promotion.ends_at,
    }
    merged.update({k: v for k, v in payload.items() if k in merged})
    _validate_shape(merged)

    for field in _EDITABLE:
        if field in payload:
            setattr(promotion, field, payload[field])

    if "targets" in payload:
        _validate_targets(db, payload["targets"])
        _write_targets(db, promotion.id, payload["targets"])

    db.flush()
    db.refresh(promotion)
    return promotion


def set_targets(db: Session, actor, promotion_id: int, targets: list[dict]) -> Promotion:
    """Replace the whole target set.

    Replaced rather than appended: the operator sees one list and edits it, so
    saving has to mean "this is now the list".
    """
    promotion = get_promotion(db, promotion_id)
    _validate_targets(db, targets)
    _write_targets(db, promotion.id, targets)
    db.refresh(promotion)
    return promotion


def _serialize(promotion: Promotion) -> dict:
    def enum_value(value):
        return value.value if hasattr(value, "value") else value

    return {
        "id": promotion.id,
        "name": promotion.name,
        "type": enum_value(promotion.type),
        "discount_percent": promotion.discount_percent,
        "discount_amount": promotion.discount_amount,
        "buy_quantity": promotion.buy_quantity,
        "get_quantity": promotion.get_quantity,
        "get_discount_percent": promotion.get_discount_percent,
        "starts_at": promotion.starts_at,
        "ends_at": promotion.ends_at,
        "is_active": promotion.is_active,
        "targets": [
            {
                "id": target.id,
                "target_type": enum_value(target.target_type),
                "target_id": target.target_id,
            }
            for target in promotion.targets
        ],
    }


def list_promotions(db: Session) -> list[dict]:
    """Newest first — the operator is usually looking for what they just made."""
    return [
        _serialize(promotion)
        for promotion in db.execute(
            select(Promotion).order_by(Promotion.id.desc())
        ).scalars()
    ]


def promotion_detail(db: Session, promotion_id: int) -> dict:
    return _serialize(get_promotion(db, promotion_id))
