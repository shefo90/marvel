"""Refuse a write built on a version of the row that has since moved.

Open question 4: two operators open the same product, both edit, both save, and
the second save silently discards the first. Nobody is told. The first operator
finds out when they notice their change is gone, which may be never.

The check is a comparison, not a lock. Nothing is held between the read and the
write -- holding a row lock across an operator's coffee break is how a
back-office becomes unusable -- so this is optimistic in the usual sense: let
both edits proceed, and refuse the one that turns out to have been built on
stale data.

``updated_at`` is the version. Every table this guards already has it, driven by
``onupdate=func.now()``, so there is no version column to add and no migration.
Its resolution is Postgres's microsecond, which is finer than two operators can
be told apart by.

**Absent means unchecked, deliberately.** A payload without
``expected_updated_at`` behaves exactly as it did before this module existed.
The alternative -- mandatory -- would be safer in principle and would have
broken every caller on the day it shipped. The admin UI closes the gap from its
side by sending the field from its service layer, so there is one place that has
to remember rather than one per screen.

One consequence worth stating: because ``now()`` is the transaction timestamp,
two writes inside one transaction share an ``updated_at``. A caller that reads,
writes and writes again without committing will not trip this on its second
write. That is correct -- it is one operator in one unit of work, which is not
the thing being guarded against.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status

FIELD = "expected_updated_at"


def guard_unmodified(row, payload: dict, *, what: str) -> None:
    """Refuse with 409 if ``row`` has changed since the caller last read it.

    Call this *before* applying any of the payload. A conflict that has already
    written half the fields would tell the operator their save failed while
    partly having succeeded, which is worse than not checking at all.
    """
    expected = payload.get(FIELD)
    if expected is None:
        return

    if isinstance(expected, str):
        # Pydantic hands over a datetime; a repository called directly from a
        # script or a test may not.
        expected = datetime.fromisoformat(expected)

    current = row.updated_at
    if current is not None and expected == current:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"this {what} was changed by someone else while you were editing it — "
            "reload to see their version, then reapply your change"
        ),
    )
