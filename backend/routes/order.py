"""Checkout endpoints — section 14's ``POST /orders`` plus order lookup.

No SQLAlchemy here: the whole write, including the idempotency claim, is one
repository call so it can be one transaction. A route that opened the
transaction would make "the idempotency row and the order commit together"
depend on this layer remembering to.

The locale is a path segment for the same reason it is on the catalog routes:
section 8A requires the URL alone to decide the language. It is validated
against the ``locales`` table so ``/api/AR/orders`` 404s instead of quietly
placing an order in an unknown language.
"""

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.order import create_order, get_order, resolve_locale
from schema.order import order_create_request, order_response

router = APIRouter(prefix="/api/{locale}", tags=["orders"])


def valid_locale(
    locale: str = Path(..., min_length=2, max_length=5),
    db: Session = Depends(get_db),
) -> str:
    return resolve_locale(db, locale)


@router.post(
    "/orders",
    response_model=order_response,
    status_code=status.HTTP_201_CREATED,
)
def place_order(
    response: Response,
    payload: order_create_request,
    locale: str = Depends(valid_locale),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Convert a server-side cart into an order, exactly once.

    The ``Idempotency-Key`` header is mandatory. A replay returns the stored
    response verbatim — same ``order_number``, so section 5's ``purchase`` event
    keeps one stable ``transaction_id`` across a refresh or a back navigation,
    and section 15's "purchase fires once" holds server-side rather than relying
    on the browser to behave.
    """
    status_code, body, replayed = create_order(
        db, locale=locale, idempotency_key=idempotency_key, payload=payload
    )
    response.status_code = status_code
    # Lets the caller (and S7's acceptance tests) tell a replay from a first
    # write without diffing the body.
    response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    # An order is per-shopper state: never store it in a shared or browser cache.
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/orders/{order_number}", response_model=order_response)
def read_order(
    response: Response,
    order_number: str,
    locale: str = Depends(valid_locale),
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Read one order by its immutable ``order_number``.

    Guest checkout means there is no session to authorize against, so the caller
    presents the email or phone the order was placed with. The order's own
    ``locale`` field is the one it was placed in — the path locale selects the
    language of the surrounding page, not the content of a frozen snapshot.
    """
    response.headers["Cache-Control"] = "no-store"
    return get_order(db, order_number=order_number, email=email, phone=phone)
