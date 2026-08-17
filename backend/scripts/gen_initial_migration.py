"""Generate the initial Alembic migration body without needing a live database.

The first migration against an empty database is deterministic: create
everything in ``Base.metadata``. That does not require introspecting a server,
so this renders it offline from the PostgreSQL dialect alone.

Writes the rendered upgrade/downgrade bodies to stdout. Run from the backend
root:  python scripts/gen_initial_migration.py > alembic/_initial_body.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic.autogenerate import render_python_code  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import ops  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import sort_tables_and_constraints  # noqa: E402

import models  # noqa: E402,F401
from core.db import Base  # noqa: E402

metadata = Base.metadata

# sort_tables_and_constraints returns (table, constraints) pairs in dependency
# order, and yields (None, [fkcs]) for constraints that must be applied AFTER
# all tables because they form a cycle — exactly the products <-> product_variants
# case created by the use_alter default-variant guard.
sorted_pairs = sort_tables_and_constraints(list(metadata.tables.values()))

create_ops = []
deferred_fks = []

for table, constraints in sorted_pairs:
    if table is None:
        deferred_fks.extend(constraints)

# A deferred FK must NOT appear inline in its CREATE TABLE — that is precisely
# why it was deferred. CreateTableOp.from_table() renders every constraint
# attached to the table, so the cyclic ones are detached first and re-added
# below as explicit ALTER TABLE ops.
for fkc in deferred_fks:
    fkc.table.constraints.discard(fkc)

for table, constraints in sorted_pairs:
    if table is None:
        continue
    create_ops.append(ops.CreateTableOp.from_table(table))
    for index in sorted(table.indexes, key=lambda i: i.name or ""):
        create_ops.append(ops.CreateIndexOp.from_index(index))

for fkc in deferred_fks:
    cols = "_".join(e.parent.name for e in fkc.elements)
    fk_name = fkc.name if isinstance(fkc.name, str) else f"fk_{fkc.table.name}_{cols}"
    create_ops.append(
        ops.CreateForeignKeyOp(
            fk_name,
            fkc.table.name,
            fkc.elements[0].column.table.name,
            [e.parent.name for e in fkc.elements],
            [e.column.name for e in fkc.elements],
            ondelete=fkc.ondelete,
            onupdate=fkc.onupdate,
        )
    )

drop_ops = []
for fkc in deferred_fks:
    cols = "_".join(e.parent.name for e in fkc.elements)
    fk_name = fkc.name if isinstance(fkc.name, str) else f"fk_{fkc.table.name}_{cols}"
    drop_ops.append(ops.DropConstraintOp(fk_name, fkc.table.name, type_="foreignkey"))
for table, constraints in reversed(sorted_pairs):
    if table is None:
        continue
    drop_ops.append(ops.DropTableOp(table.name))

mc = MigrationContext.configure(dialect=postgresql.dialect())

upgrade_body = render_python_code(ops.UpgradeOps(ops=create_ops), migration_context=mc)
downgrade_body = render_python_code(ops.DowngradeOps(ops=drop_ops), migration_context=mc)

TEMPLATE = '''"""initial schema — S1 commerce core

Creates all {n} tables of the S1 data model: catalog, localization, identity,
attribution, cart, orders, payments, addresses and the Tier-2 fulfilment tables.

Generated offline from Base.metadata by scripts/gen_initial_migration.py — the
first migration against an empty database is deterministic, so it does not need
a live server to produce.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
{upgrade}


def downgrade() -> None:
{downgrade}
'''

out = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic",
    "versions",
    "0001_initial_schema.py",
)
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    fh.write(
        TEMPLATE.format(
            n=len(metadata.tables), upgrade=upgrade_body, downgrade=downgrade_body
        )
    )

print(f"wrote {out}")
print(f"tables: {len(metadata.tables)}  deferred_fks: {len(deferred_fks)}")
