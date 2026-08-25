"""Exponential backoff with jitter, as section 13 requires.

Jitter is not decoration. Retries here are overwhelmingly caused by a third
party being unavailable, which means every job that failed did so at roughly the
same moment; a pure exponential schedule sends them all back at roughly the same
moment too, and keeps doing it. Spreading each delay across a window breaks that
convoy up.

Injectable randomness so the schedule can be asserted exactly in tests, since a
backoff that silently collapses to zero is invisible until production.
"""

from __future__ import annotations

import random
from typing import Callable

from core.config import JOB_RETRY_BASE_SECONDS, JOB_RETRY_CAP_SECONDS

JITTER = 0.2


def delay_seconds(
    attempt: int,
    *,
    base: float = JOB_RETRY_BASE_SECONDS,
    cap: float = JOB_RETRY_CAP_SECONDS,
    rand: Callable[[], float] = random.random,
) -> float:
    """Delay before attempt number ``attempt`` (1 = the first retry).

    ``base * 2 ** (attempt - 1)``, capped, then spread by +/- JITTER. The cap is
    applied before the jitter, so the returned value can exceed it by the jitter
    fraction -- which is the point: a hard ceiling shared by every job is
    another convoy.
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    raw = min(base * (2 ** (attempt - 1)), cap)
    spread = raw * JITTER
    return raw + (rand() * 2 - 1) * spread
