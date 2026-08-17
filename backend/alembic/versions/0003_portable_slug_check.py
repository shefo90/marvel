"""replace the slug format check with a collation-independent denylist

The original constraint was::

    slug = lower(slug) AND slug ~ '^[[:alnum:]]+(-[[:alnum:]]+)*$'

``slug`` is declared COLLATE "C" so Arabic strings compare byte-exactly and the
``(locale, slug)`` unique index stays predictable. But under the C collation
POSIX character classes are ASCII-only, so ``[[:alnum:]]`` rejects every Arabic
letter — every Arabic slug failed to insert.

The failure is easy to miss: testing the same regex against a bound parameter
passes, because the parameter carries the database default collation rather than
the column's.

Replaced with a denylist. The denied sets are pure ASCII, so they behave
identically under any collation, and Arabic passes by not being in them.

Revision ID: 0003_portable_slug_check
Revises: 0002_integrity_triggers
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_portable_slug_check"
down_revision: Union[str, None] = "0002_integrity_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["product_translations", "category_translations", "collection_translations"]

NEW_CHECK = (
    "slug = lower(slug) "
    "AND length(slug) > 0 "
    "AND slug !~ '[[:space:]]' "
    "AND slug !~ '[A-Z]' "
    "AND slug !~ '[!\"#$%&''''()*+,./:;<=>?@[\\\\\\]^`{|}~]' "
    "AND slug NOT LIKE '-%' "
    "AND slug NOT LIKE '%-' "
    "AND slug NOT LIKE '%--%'"
)

OLD_CHECK = "slug = lower(slug) AND slug ~ '^[[:alnum:]]+(-[[:alnum:]]+)*$'"


def upgrade() -> None:
    for table in TABLES:
        name = f"ck_{table}_slug_format"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, NEW_CHECK)


def downgrade() -> None:
    for table in TABLES:
        name = f"ck_{table}_slug_format"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, OLD_CHECK)
