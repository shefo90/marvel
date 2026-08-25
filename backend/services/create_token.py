"""JWT encode/decode plus the HTTPBearer dependencies.

Two token types, both signed with SECRET_KEY/ALGORITHM, each carrying a ``type``
claim that is verified on decode so the two are never interchangeable. A
``scope`` claim separates staff tokens from shopper tokens for the same reason:
a shopper token must never satisfy a staff endpoint.

Stateless — imports no models, repositories or routes.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)

ACCESS_TYPE = "access_token"
REFRESH_TYPE = "refresh_token"

SCOPE_STAFF = "staff"
SCOPE_CUSTOMER = "customer"

# Separate schemes so both appear in the OpenAPI docs.
access_scheme = HTTPBearer(description="Access token")
refresh_scheme = HTTPBearer(description="Refresh token")
customer_scheme = HTTPBearer(description="Shopper access token")
optional_customer_scheme = HTTPBearer(auto_error=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(claims: dict) -> str:
    payload = dict(claims)
    payload.update(
        {
            "type": ACCESS_TYPE,
            "exp": _now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            "iat": _now(),
        }
    )
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(claims: dict) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at).

    The jti is what the persisted ``refresh_token`` row is looked up by during
    rotation; the token itself is stored hashed, never in plaintext.
    """
    jti = str(uuid.uuid4())
    expires = _now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = dict(claims)
    payload.update({"type": REFRESH_TYPE, "jti": jti, "exp": expires, "iat": _now()})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM), jti, expires


def _decode(token: str, expected_type: str, expected_scope: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong token type"
        )
    if payload.get("scope") != expected_scope:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong token scope"
        )
    return payload


def get_accesstoken(
    creds: HTTPAuthorizationCredentials = Depends(access_scheme),
) -> dict:
    return _decode(creds.credentials, ACCESS_TYPE, SCOPE_STAFF)


def get_refresh_token(
    creds: HTTPAuthorizationCredentials = Depends(refresh_scheme),
) -> dict:
    return _decode(creds.credentials, REFRESH_TYPE, SCOPE_STAFF)


def get_customer_token(
    creds: HTTPAuthorizationCredentials = Depends(customer_scheme),
) -> dict:
    return _decode(creds.credentials, ACCESS_TYPE, SCOPE_CUSTOMER)


def get_customer_refresh_token(
    creds: HTTPAuthorizationCredentials = Depends(refresh_scheme),
) -> dict:
    return _decode(creds.credentials, REFRESH_TYPE, SCOPE_CUSTOMER)


def decode_customer_refresh(token: str) -> dict:
    """Verify a shopper refresh token that did not arrive in a header.

    The storefront keeps its refresh token in an httpOnly cookie, so there is no
    ``Authorization`` header to depend on. Same verification as
    ``get_customer_refresh_token`` -- signature, type and scope -- reached
    without FastAPI's security scheme, which insists on a header it will not
    find.
    """
    return _decode(token, REFRESH_TYPE, SCOPE_CUSTOMER)


def get_optional_customer(
    creds: HTTPAuthorizationCredentials | None = Depends(optional_customer_scheme),
) -> dict | None:
    """Guest-tolerant. Returns None when no bearer token is present.

    Used by the cart endpoints: a cart belongs either to an anonymous visitor
    token or to a signed-in shopper, and both must work (section 15 requires
    guest and logged-in checkout to both track correctly).
    """
    if creds is None:
        return None
    return _decode(creds.credentials, ACCESS_TYPE, SCOPE_CUSTOMER)
