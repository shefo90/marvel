"""The admin gate — who is allowed to write to the catalog.

The rule these tests defend is the one ``register_staff`` already established:
**the token's ``access_level`` claim is not trusted on its own.** It is minted at
login and stays valid until the access token expires, so a staff member demoted
or deactivated five minutes ago still presents their old claim. Every admin
write re-reads the actor from the database.

Trusting the claim would look correct in every normal test — the claim and the
row agree right up until the moment someone's access is revoked, which is
exactly when it matters.
"""

import pytest
from fastapi import HTTPException

from models.users import User
from repositories.staff_access import require_staff
from services.role_access_level import LEVEL_ADMIN, LEVEL_CATALOG


def _staff(db, role: str, *, is_active: bool = True) -> User:
    """A staff row that exists only for this test — the session is rolled back."""
    user = User(
        email=f"gate-{role}-{is_active}@example.test",
        password_hash="not-a-real-hash",
        full_name=f"Gate {role}",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def _claims(user: User, access_level: int) -> dict:
    """What a login-minted access token carries."""
    return {"id": user.id, "role": user.role, "access_level": access_level}


def test_catalog_role_may_write_the_catalog(db):
    user = _staff(db, "catalog")

    actor = require_staff(db, _claims(user, 2), LEVEL_CATALOG)

    assert actor.id == user.id


def test_support_role_may_not_write_the_catalog(db):
    user = _staff(db, "support")

    with pytest.raises(HTTPException) as exc:
        require_staff(db, _claims(user, 1), LEVEL_CATALOG)

    assert exc.value.status_code == 403


def test_catalog_role_may_not_edit_cogs(db):
    """COGS feeds contribution_profit, so it sits behind the admin gate."""
    user = _staff(db, "catalog")

    with pytest.raises(HTTPException) as exc:
        require_staff(db, _claims(user, 2), LEVEL_ADMIN)

    assert exc.value.status_code == 403


def test_deactivated_staff_are_refused(db):
    user = _staff(db, "admin", is_active=False)

    with pytest.raises(HTTPException) as exc:
        require_staff(db, _claims(user, 4), LEVEL_CATALOG)

    assert exc.value.status_code == 401


def test_demotion_applies_before_the_token_expires(db):
    """The reason the actor is re-read rather than taken from the claim.

    This staff member was an admin when the token was minted and still carries
    ``access_level: 4``. They have since been demoted to support. The stale
    claim must not get them past the catalog gate.
    """
    user = _staff(db, "support")

    with pytest.raises(HTTPException) as exc:
        require_staff(db, _claims(user, LEVEL_ADMIN), LEVEL_CATALOG)

    assert exc.value.status_code == 403


def test_unknown_actor_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        require_staff(db, {"id": 10**9, "access_level": 4}, LEVEL_CATALOG)

    assert exc.value.status_code == 401
