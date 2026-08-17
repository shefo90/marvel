"""Authentication — credential verification and token issuance.

Two token families, never interchangeable. ``services.create_token`` verifies
both a ``type`` claim and a ``scope`` claim on decode, so a shopper token
presented to a staff endpoint fails at the dependency, before any repository
code runs.

**What the staff access token carries and why.** ``access_level`` is baked in at
login so a protected endpoint gates on an integer comparison instead of a DB
round-trip on every request. The cost is that the claim is a snapshot: a staff
member demoted at 10:00 keeps the old level until their access token expires.
That is why anything genuinely destructive — staff registration, money
corrections — re-reads the actor from the database rather than trusting the
claim (see ``repositories.register.register_staff``).

**What the shopper access token carries and why not.** Design section 4 pins
``customers.id`` as internal and "never exposed to the browser". A JWT payload is
base64, not encryption, so the browser can read every claim in it. The shopper
token therefore carries ``public_id`` — the opaque UUID that exists for exactly
this — and :func:`customer_from_token` maps it back to the internal row.

**Refresh tokens are stored hashed.** The database holds ``sha256(token)``, so a
dump of ``refresh_token`` or ``customer_refresh_token`` yields nothing that can
be replayed.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import ACCESS_TOKEN_EXPIRE_MINUTES
from models.customer_refresh_token import CustomerRefreshToken
from models.customers import Customer
from models.refresh_token import RefreshToken
from models.users import User
from repositories.register import find_customer_by_identity, normalize_email, sha256_hex
from schema.login import login_request
from services.create_token import (
    SCOPE_CUSTOMER,
    SCOPE_STAFF,
    create_access_token,
    create_refresh_token,
)
from services.hash_password import verify_password
from services.role_access_level import set_access_level

# Online-guessing brake on shopper accounts. ``customer_credential`` already
# carries the two columns this needs, so the lockout is durable rather than
# living in a process-local counter that resets on every deploy. Staff accounts
# have no equivalent columns in the schema and are left to network-level
# protection — noted rather than silently unimplemented.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_in() -> int:
    return ACCESS_TOKEN_EXPIRE_MINUTES * 60


def issue_staff_tokens(db: Session, user: User) -> dict:
    """Mint an access+refresh pair for a staff user and persist the refresh row.

    Flushes but does not commit — login and rotation both wrap this in their own
    transaction, and rotation must revoke the old row and insert the new one
    atomically or a crash between the two would leave the user with no valid
    refresh token at all.
    """
    access = create_access_token(
        {
            "sub": user.email,
            "id": user.id,
            "email": user.email,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "access_level": set_access_level(user),
            "scope": SCOPE_STAFF,
        }
    )
    refresh, jti, expires = create_refresh_token(
        {"sub": user.email, "id": user.id, "scope": SCOPE_STAFF}
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=sha256_hex(refresh),
            jti=jti,
            expires_at=expires,
        )
    )
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": _expires_in(),
        "scope": SCOPE_STAFF,
    }


def issue_customer_tokens(db: Session, customer: Customer) -> dict:
    """Mint an access+refresh pair for a shopper. See the module docstring on
    why ``public_id`` appears here and ``customers.id`` does not."""
    public_id = str(customer.public_id)
    access = create_access_token(
        {
            "sub": customer.email or public_id,
            "public_id": public_id,
            "email": customer.email,
            "scope": SCOPE_CUSTOMER,
        }
    )
    refresh, jti, expires = create_refresh_token(
        {"sub": public_id, "public_id": public_id, "scope": SCOPE_CUSTOMER}
    )
    db.add(
        CustomerRefreshToken(
            customer_id=customer.id,
            token_hash=sha256_hex(refresh),
            jti=jti,
            expires_at=expires,
        )
    )
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": _expires_in(),
        "scope": SCOPE_CUSTOMER,
    }


def login_staff(db: Session, payload: login_request) -> dict:
    """Verify staff credentials and issue a token pair.

    A missing user and a wrong password return the identical 401. Distinguishing
    them turns the login endpoint into an account-enumeration oracle.
    """
    email_norm = normalize_email(payload.email)
    # lower() so the lookup rides uq_users_email, the expression index that also
    # makes staff login case-insensitive.
    user = db.execute(
        select(User).where(func.lower(User.email) == email_norm)
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise _INVALID
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled"
        )

    user.last_login_at = _now()
    tokens = issue_staff_tokens(db, user)
    db.commit()
    return tokens


def login_customer(db: Session, payload: login_request) -> dict:
    """Verify shopper credentials and issue a token pair.

    The failed-attempt counter is persisted on the *failure* path too, so the
    lockout survives the rollback-free path a plain read-only login would take.
    """
    customer = find_customer_by_identity(db, email=payload.email)
    credential = customer.credential if customer is not None else None
    if credential is None:
        raise _INVALID
    if not credential.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled"
        )
    if credential.locked_until is not None and credential.locked_until > _now():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account temporarily locked after repeated failed logins",
        )

    if not verify_password(payload.password, credential.password_hash):
        credential.failed_login_count += 1
        if credential.failed_login_count >= MAX_FAILED_LOGINS:
            credential.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        raise _INVALID

    credential.failed_login_count = 0
    credential.locked_until = None
    credential.last_login_at = _now()
    tokens = issue_customer_tokens(db, customer)
    db.commit()
    return tokens


def customer_from_token(db: Session, claims: dict) -> Customer:
    """Resolve a decoded shopper access token to a live ``customers`` row.

    This is the bridge every shopper-scoped endpoint needs, because the token
    deliberately carries ``public_id`` rather than the internal id. Cart and
    order code should call this instead of reading an id claim that is not there.
    """
    try:
        public_id = UUID(str(claims.get("public_id")))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        )
    customer = db.execute(
        select(Customer).where(Customer.public_id == public_id)
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        )
    return customer
