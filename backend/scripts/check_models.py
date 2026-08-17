"""Import every model, configure mappers, and print the metadata inventory.

Run from the backend root:  python scripts/check_models.py

Catches the failure mode that a per-file review cannot: a relationship whose
string target does not resolve, or a table missing from models/__init__.py and
therefore from every migration.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import configure_mappers  # noqa: E402

import models  # noqa: E402,F401
from core.db import Base  # noqa: E402

configure_mappers()

tables = sorted(Base.metadata.tables)
print("tables registered:", len(tables))
for name in tables:
    table = Base.metadata.tables[name]
    print(
        f"  {name:<32} cols={len(table.columns):<3} "
        f"fk={len(table.foreign_keys):<3} idx={len(table.indexes)}"
    )

exported = len(models.__all__)
print()
print("models.__all__:", exported)
missing = set(tables) - {
    getattr(models, n).__tablename__ for n in models.__all__
}
if missing:
    print("NOT EXPORTED FROM models/__init__.py:", sorted(missing))
    sys.exit(1)
print("every table is exported")
