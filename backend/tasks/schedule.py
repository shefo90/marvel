"""Recurring work, and how it recurs without a second process.

There is no beat process and no cron. Each tick, the worker checks whether a
row already exists for each recurring kind and inserts one for
``now + interval`` if not. The partial unique index on ``dedupe_key`` makes that
safe with any number of workers: they all try, exactly one wins, the losers get
``None`` back from ``enqueue``.

Because a successful job deletes its row, the next occurrence is scheduled by
the tick that follows the run -- so the real period is the interval plus at most
one poll. That is intentional for sweeps and would be wrong for anything needing
a precise wall-clock time, which nothing here does.

A dead-lettered occurrence does not stop the schedule: the unique index only
constrains pending and running rows, so the next tick queues the next
occurrence while the dead row stays put for the operator to find.
"""

from __future__ import annotations

from datetime import timedelta

RECURRING: dict[str, timedelta] = {
    "carts.sweep_abandoned": timedelta(minutes=15),
    "carts.sweep_expired": timedelta(hours=6),
}
