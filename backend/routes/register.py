"""Registration endpoints — staff (admin-gated) and shoppers (open).

No SQLAlchemy in this layer; the repository owns every query, every rule and the
commit.

The locale is a path segment for the same reason the catalog routes use one
(design section 6.3): the URL is the only thing that decides language, never a
header and never an IP. Auth responses carry no catalog text today, but a
locale-less auth URL would be the one exception in the API surface and would
have to be retrofitted the first time an error message needs translating.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.register import register_customer, register_staff
from routes.product import valid_locale
from schema.register import (
    customer_register_request,
    customer_response,
    staff_register_request,
    staff_response,
)
from services.create_token import get_accesstoken

router = APIRouter(prefix="/api/{locale}/auth", tags=["auth"])


@router.post(
    "/staff/register",
    response_model=staff_response,
    status_code=status.HTTP_201_CREATED,
)
def register_staff_account(
    payload: staff_register_request,
    locale: str = Depends(valid_locale),
    actor_claims: dict = Depends(get_accesstoken),
    db: Session = Depends(get_db),
):
    """Create a staff account. Requires an admin access token.

    ``get_accesstoken`` rejects a shopper token outright (wrong ``scope``), so
    this endpoint cannot be reached with a customer credential. The admin level
    check itself lives in the repository, where it is re-verified against the
    live user row rather than trusted from the token claim.
    """
    return register_staff(db, actor_claims, payload)


@router.post(
    "/register",
    response_model=customer_response,
    status_code=status.HTTP_201_CREATED,
)
def register_customer_account(
    payload: customer_register_request,
    locale: str = Depends(valid_locale),
    db: Session = Depends(get_db),
):
    """Create a shopper login.

    Returns the customer, not a token pair: registration and session creation
    stay separate calls so there is exactly one code path that issues shopper
    tokens. Clients call ``POST /auth/login`` next.

    A guest who has already ordered under this email or phone is resolved to
    their existing ``customers`` row rather than duplicated (design section 11A).
    """
    return register_customer(db, payload)
