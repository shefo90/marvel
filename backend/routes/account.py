"""The signed-in shopper: their session, their orders, their addresses.

Separate from ``routes/auth.py`` rather than folded into it. That file's
``/auth/login`` returns a token pair in the body and is what the header-based
clients use; this one puts the refresh token in an httpOnly cookie and never in
a body. Both are legitimate, they suit different clients, and changing the
first one's contract to serve the second would have broken every caller of a
tested endpoint to save a file.

Everything below ``/account`` other than the session endpoints is scoped by the
token, never by an id in the path. ``GET /account/orders/{order_number}`` returns
the order only if it belongs to the caller, which is why the guest lookup in
``routes/order.py`` -- which proves entitlement with the placing contact's email
or phone -- stays where it is instead of being generalised. Two different proofs
of the same right, for two kinds of visitor.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, Request, Response
from fastapi import status as http_status
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.account import (
    archive_address,
    create_address,
    list_addresses,
    list_customer_orders,
    read_customer_order,
    update_address,
)
from repositories.login import customer_from_token, login_customer
from repositories.refresh_token import revoke_customer_token, rotate_customer_token
from routes.product import valid_locale
from schema.account import (
    account_address,
    account_address_create,
    account_address_update,
    account_order_detail,
    account_order_row,
    account_profile,
    account_session_response,
)
from schema.login import login_request
from services.create_token import decode_customer_refresh, get_customer_token
from services.session_cookies import (
    clear_session,
    issue_session,
    require_csrf,
    require_refresh_cookie,
)

router = APIRouter(prefix="/api/{locale}/account", tags=["account"])


def current_customer(
    claims: dict = Depends(get_customer_token),
    db: Session = Depends(get_db),
):
    """The signed-in shopper, resolved from the access token.

    The token carries ``public_id``, not the internal row id, so this bridge is
    mandatory -- reading an ``id`` claim would read one that is not there.
    """
    return customer_from_token(db, claims)


# --- session -------------------------------------------------------------

@router.post("/session", response_model=account_session_response)
def sign_in(
    payload: login_request,
    request: Request,
    response: Response,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Sign in. The refresh token goes to a cookie; only the access token is
    returned, and it is meant to be held in memory."""
    tokens = login_customer(db, payload)
    csrf = issue_session(request, response, tokens["refresh_token"])
    return {
        "access_token": tokens["access_token"],
        "token_type": tokens.get("token_type", "bearer"),
        "csrf_token": csrf,
    }


@router.post("/session/refresh", response_model=account_session_response)
def refresh_session(
    request: Request,
    response: Response,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Rotate the session from the cookie alone.

    CSRF is checked before the cookie is read. Order matters only for the error
    the caller sees, but the clearer of the two is worth having: a request with
    no CSRF header is a misconfigured client, not an expired session, and
    telling it "no session" would send someone looking in the wrong place.
    """
    require_csrf(request)
    raw = require_refresh_cookie(request)
    claims = decode_customer_refresh(raw)

    tokens = rotate_customer_token(db, raw, claims)
    csrf = issue_session(request, response, tokens["refresh_token"])
    return {
        "access_token": tokens["access_token"],
        "token_type": tokens.get("token_type", "bearer"),
        "csrf_token": csrf,
    }


@router.delete("/session", status_code=http_status.HTTP_204_NO_CONTENT)
def sign_out(
    request: Request,
    response: Response,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Sign out: revoke the stored token, then clear the cookies.

    Tolerant of a session that is already gone. Someone clicking sign out twice,
    or signing out with an expired token, wants the same outcome either way --
    and an error here would leave the cookies in place, which is the opposite of
    what they asked for.
    """
    require_csrf(request)
    raw = request.cookies.get("marvel_refresh")
    if raw:
        try:
            revoke_customer_token(db, raw, decode_customer_refresh(raw))
        except Exception:  # noqa: BLE001 - see docstring
            pass
    # Nothing is returned. Building a new Response here would discard the
    # injected one, and with it the delete-cookie headers clear_session just
    # set -- a sign-out that revokes the token server-side, reports 204, and
    # leaves the browser holding both cookies.
    clear_session(response)


# --- profile -------------------------------------------------------------

@router.get("/me", response_model=account_profile)
def read_profile(
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
):
    return customer


# --- orders --------------------------------------------------------------

@router.get("/orders", response_model=list[account_order_row])
def read_orders(
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    """This shopper's orders, newest first."""
    return list_customer_orders(db, customer.id)


@router.get("/orders/{order_number}", response_model=account_order_detail)
def read_order(
    order_number: str,
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    """One order, if it is this shopper's.

    An order belonging to somebody else is a 404 rather than a 403: confirming
    that an order number exists is itself worth something to whoever is guessing.
    """
    return read_customer_order(db, customer.id, order_number)


# --- addresses -----------------------------------------------------------

@router.get("/addresses", response_model=list[account_address])
def read_addresses(
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    return list_addresses(db, customer.id)


@router.post(
    "/addresses",
    response_model=account_address,
    status_code=http_status.HTTP_201_CREATED,
)
def add_address(
    payload: account_address_create,
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    address = create_address(db, customer.id, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(address)
    return address


@router.patch("/addresses/{address_id}", response_model=account_address)
def edit_address(
    address_id: int,
    payload: account_address_update,
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    address = update_address(
        db, customer.id, address_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(address)
    return address


@router.delete("/addresses/{address_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def remove_address(
    address_id: int,
    locale: str = Depends(valid_locale),
    customer=Depends(current_customer),
    db: Session = Depends(get_db),
):
    """Archive, not delete.

    ``order_addresses`` snapshots the address onto the order, so an old order is
    not damaged by this -- but ``addresses.archived_at`` exists precisely so the
    row survives, and nothing else in this schema destroys a customer record.
    """
    archive_address(db, customer.id, address_id)
    db.commit()
