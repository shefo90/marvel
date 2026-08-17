"""Shared FastAPI dependencies for the ``/api/admin`` namespace.

The authorization rule itself lives in ``repositories.staff_access`` — this
module only wires it into FastAPI, keeping the layering the project already
follows: routes do HTTP, repositories decide.

Usage reads as intent rather than as a number::

    actor: User = Depends(staff_at_least(LEVEL_CATALOG))
"""

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from core.db import get_db
from models.users import User
from repositories.staff_access import require_staff
from services.create_token import get_accesstoken


def staff_at_least(minimum_level: int) -> Callable[..., User]:
    """Build a dependency admitting only staff at or above ``minimum_level``.

    Returns the resolved ``User`` so endpoints can attribute money changes to a
    person — admin writes set ``app.actor_user_id`` for the Approach-A audit
    trigger rather than letting it record ``actor_type='system'``.
    """

    def dependency(
        claims: dict = Depends(get_accesstoken),
        db: Session = Depends(get_db),
    ) -> User:
        return require_staff(db, claims, minimum_level)

    return dependency
