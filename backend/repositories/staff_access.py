"""Resolve and authorize the staff member behind an admin write.

Every ``/api/admin`` endpoint goes through here. The rule is the one
``repositories.register.register_staff`` established, and it is the reason this
is a database read rather than a claim check:

    The token's ``access_level`` claim is not trusted on its own. It was minted
    at login and stays valid until the access token expires, so a staff member
    demoted or deactivated five minutes ago still carries their old claim.

Trusting the claim looks correct in every ordinary test, because the claim and
the row agree right up until the moment someone's access is revoked — which is
precisely when the check has to work.

The resolved ``User`` is returned rather than a bare boolean because callers
need the actor's id to attribute money changes: admin writes set
``app.actor_user_id`` so the Approach-A audit trigger records a person rather
than falling back to ``actor_type='system'`` (audit finding F5).
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.users import User
from services.role_access_level import set_access_level


def require_staff(db: Session, claims: dict, minimum_level: int) -> User:
    """Return the acting staff member, or raise 401/403.

    401 when the actor cannot act at all (unknown or deactivated); 403 when they
    are a real, active user whose role is simply not senior enough. Keeping the
    two distinct matters: a deactivated admin should not be told that their
    problem is the role.
    """
    actor = db.get(User, claims.get("id"))
    if actor is None or not actor.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid actor"
        )

    if set_access_level(actor) < minimum_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient staff role for this action",
        )

    return actor
