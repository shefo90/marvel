"""Refresh-token rotation, for both token families.

The contract, identical for staff and shoppers:

1. Look the stored row up **by ``jti``**, never by scanning for the token.
2. Reject if the row is missing, revoked or expired.
3. Confirm ``sha256(presented token)`` matches the stored hash.
4. Mark the old row revoked — ``revoked = true`` **and** ``revoked_at`` set,
   because ``ck_refresh_token_revoked`` refuses a row where the two disagree.
5. Issue a new access+refresh pair and persist the new row.
6. Commit both writes in one transaction.

Step 3 is not redundant with step 1. The ``jti`` is a plaintext claim inside the
JWT, so anyone holding *any* token from this issuer can read one; the signature
check proves the token was minted here, and the hash comparison proves it is the
same token that was stored. Without it, a token forged with a stolen signing key
and a copied ``jti`` would rotate successfully.

Steps 4 and 5 share a transaction deliberately. Revoking first and committing
separately would leave a client with no valid refresh token if the second write
failed — an unrecoverable logout caused by a transient database error.

**Reuse of an already-rotated token is rejected but not escalated.** The design
specifies "reject if missing, revoked, or expired" and that is what runs here. A
stricter reading of a replayed refresh token is that the token family is
compromised and every sibling row should be revoked. That is a real hardening
step, and it is deliberately *not* taken silently — it is a policy decision, and
adding it later is a one-line change at the marked point below.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.customer_refresh_token import CustomerRefreshToken
from models.customers import Customer
from models.refresh_token import RefreshToken
from models.users import User
from repositories.login import issue_customer_tokens, issue_staff_tokens
from repositories.register import sha256_hex

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jti(claims: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims.get("jti")))
    except (TypeError, ValueError):
        raise _INVALID


def _consume(db: Session, model, raw_token: str, claims: dict):
    """Validate a stored refresh row and revoke it. Returns the revoked row.

    Shared by both families because the rules are identical — divergence here
    would mean one of the two token types quietly acquiring weaker checks.
    """
    row = db.execute(
        select(model).where(model.jti == _jti(claims))
    ).scalar_one_or_none()
    if row is None:
        raise _INVALID
    if row.revoked:
        # <- token replay after rotation. Escalation point: revoking the whole
        # family for this subject would go here. See the module docstring.
        raise _INVALID

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _now():
        raise _INVALID

    if row.token_hash != sha256_hex(raw_token):
        raise _INVALID

    row.revoked = True
    row.revoked_at = _now()
    db.flush()
    return row


def rotate_staff_token(db: Session, raw_token: str, claims: dict) -> dict:
    row = _consume(db, RefreshToken, raw_token, claims)

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        # Deactivating a staff account must end their sessions at the next
        # rotation, not merely stop new logins.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled"
        )

    tokens = issue_staff_tokens(db, user)
    db.commit()
    return tokens


def rotate_customer_token(db: Session, raw_token: str, claims: dict) -> dict:
    row = _consume(db, CustomerRefreshToken, raw_token, claims)

    customer = db.get(Customer, row.customer_id)
    credential = customer.credential if customer is not None else None
    if customer is None or credential is None or not credential.is_active:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled"
        )

    tokens = issue_customer_tokens(db, customer)
    db.commit()
    return tokens
