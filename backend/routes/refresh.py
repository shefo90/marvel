"""Refresh rotation endpoints.

The refresh token arrives in the ``Authorization`` header, not a request body,
so it never lands in a body-logging proxy or a client's query string.

Each handler takes the header twice, deliberately: ``get_refresh_token`` returns
the *decoded, signature-verified* claims, while ``refresh_scheme`` returns the
raw string the repository must hash to compare against the stored value. Both
are needed — the claims give us the ``jti`` to look the row up by, and the raw
token proves the caller holds the token that row was created from.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.refresh_token import rotate_customer_token, rotate_staff_token
from routes.product import valid_locale
from schema.refresh_token import refresh_response
from services.create_token import (
    get_customer_refresh_token,
    get_refresh_token,
    refresh_scheme,
)

router = APIRouter(prefix="/api/{locale}/auth", tags=["auth"])


@router.post("/staff/refresh", response_model=refresh_response)
def staff_refresh(
    locale: str = Depends(valid_locale),
    claims: dict = Depends(get_refresh_token),
    creds: HTTPAuthorizationCredentials = Depends(refresh_scheme),
    db: Session = Depends(get_db),
):
    """Rotate a staff refresh token. The presented token is revoked and a fresh
    access+refresh pair is returned; replaying the old one now fails."""
    return rotate_staff_token(db, creds.credentials, claims)


@router.post("/refresh", response_model=refresh_response)
def customer_refresh(
    locale: str = Depends(valid_locale),
    claims: dict = Depends(get_customer_refresh_token),
    creds: HTTPAuthorizationCredentials = Depends(refresh_scheme),
    db: Session = Depends(get_db),
):
    """Rotate a shopper refresh token. Same contract as the staff path, against
    the separate ``customer_refresh_token`` table."""
    return rotate_customer_token(db, creds.credentials, claims)
