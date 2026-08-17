"""Login endpoints for both identity families.

Staff and shoppers get separate paths rather than one endpoint that guesses.
They are separate tables (``users`` vs ``customers``, design section 2), they
mint different token scopes, and a single endpoint would have to disclose which
table an email lives in — turning login into an "is this address staff?" oracle.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.login import login_customer, login_staff
from routes.product import valid_locale
from schema.login import login_request, token_pair

router = APIRouter(prefix="/api/{locale}/auth", tags=["auth"])


@router.post("/staff/login", response_model=token_pair)
def staff_login(
    payload: login_request,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Staff login. Returns an access token carrying ``role`` and
    ``access_level``, plus a refresh token stored hashed."""
    return login_staff(db, payload)


@router.post("/login", response_model=token_pair)
def customer_login(
    payload: login_request,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Shopper login. The access token identifies the customer by ``public_id``,
    never by the internal ``customers.id`` (design section 4)."""
    return login_customer(db, payload)
