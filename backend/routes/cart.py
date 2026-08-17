"""Server-side cart endpoints — section 14's ``POST/PATCH /cart``.

No SQLAlchemy in this layer beyond the locale lookup that every localized router
performs. All cart querying, validation and commits live in
``repositories.cart``.

Transport decisions, both of which are contract rather than taste:

* **The cart identity travels in ``X-Cart-Token``.** It is an opaque, non-PII
  string the client stores and replays; that is what makes a guest cart survive
  cookie loss (section 4). A signed-in shopper does not need it — their cart is
  found by ``customer_id`` — but sending both is how a guest basket gets claimed
  at login.
* **``Idempotency-Key`` is honoured on every mutating endpoint.** A replayed key
  is a no-op that returns the same state, which is what makes section 15's rapid
  repeated clicks produce correct quantities from a flaky mobile connection.

Every response is ``Cache-Control: no-store``. A cart is per-shopper mutable
state and must never enter a shared cache.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import get_db
from models.locales import Locale
from repositories.cart import (
    add_item,
    attach_attribution,
    create_or_get_cart,
    get_cart,
    remove_item,
    reprice_cart,
    set_coupon,
    set_item_quantity,
)
from schema.cart import (
    cart_attribution_request,
    cart_coupon_request,
    cart_create_request,
    cart_item_add_request,
    cart_item_quantity_request,
    cart_response,
)
from services.create_token import get_optional_customer

router = APIRouter(prefix="/api/{locale}", tags=["cart"])


def valid_locale(
    locale: str = Path(..., min_length=2, max_length=5),
    db: Session = Depends(get_db),
) -> str:
    """Reject unknown locale segments outright.

    Same rule and same reason as ``routes.product.valid_locale``: section 8A
    forbids rendering content at HTTP 200 under an unrecognised locale.
    """
    row = db.execute(
        select(Locale).where(Locale.code == locale, Locale.is_active.is_(True))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown locale")
    return locale


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/cart", response_model=cart_response)
def create_cart(
    response: Response,
    body: cart_create_request | None = None,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    """Create or return the caller's cart. Works for guests and signed-in
    shoppers alike."""
    _no_store(response)
    attribution = (
        body.attribution.model_dump() if body and body.attribution else None
    )
    return create_or_get_cart(
        db,
        locale=locale,
        cart_token=cart_token,
        claims=claims,
        attribution=attribution,
    )


@router.get("/cart", response_model=cart_response)
def read_cart(
    response: Response,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return get_cart(db, locale=locale, cart_token=cart_token, claims=claims)


@router.post("/cart/items", response_model=cart_response)
def add_cart_item(
    response: Response,
    body: cart_item_add_request,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    """Add an item, carrying section 5's list attribution from the surface the
    shopper selected it on."""
    _no_store(response)
    return add_item(
        db,
        locale=locale,
        payload=body.model_dump(),
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


@router.patch("/cart/items/{variant_id}", response_model=cart_response)
def update_cart_item(
    response: Response,
    body: cart_item_quantity_request,
    variant_id: int = Path(..., ge=1),
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return set_item_quantity(
        db,
        locale=locale,
        variant_id=variant_id,
        quantity=body.quantity,
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


@router.delete("/cart/items/{variant_id}", response_model=cart_response)
def delete_cart_item(
    response: Response,
    variant_id: int = Path(..., ge=1),
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    _no_store(response)
    return remove_item(
        db,
        locale=locale,
        variant_id=variant_id,
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


@router.post("/cart/coupon", response_model=cart_response)
def apply_cart_coupon(
    response: Response,
    body: cart_coupon_request,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    """Apply a coupon code, or remove the current one by sending a null code."""
    _no_store(response)
    return set_coupon(
        db,
        locale=locale,
        code=body.code,
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


@router.post("/cart/reprice", response_model=cart_response)
def reprice(
    response: Response,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    """Adopt current catalog prices for lines whose price has drifted since the
    snapshot, stamping ``last_repriced_at``."""
    _no_store(response)
    return reprice_cart(
        db,
        locale=locale,
        cart_token=cart_token,
        claims=claims,
        idempotency_key=idempotency_key,
    )


@router.post("/cart/attribution", response_model=cart_response)
def set_cart_attribution(
    response: Response,
    body: cart_attribution_request,
    locale: str = Depends(valid_locale),
    cart_token: str | None = Header(None, alias="X-Cart-Token"),
    claims: dict | None = Depends(get_optional_customer),
    db: Session = Depends(get_db),
):
    """Attach acquisition data to the cart so the order snapshot can be built
    from server-side state later (section 4)."""
    _no_store(response)
    return attach_attribution(
        db,
        locale=locale,
        attribution=body.attribution.model_dump(),
        cart_token=cart_token,
        claims=claims,
    )
