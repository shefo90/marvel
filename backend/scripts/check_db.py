"""Verify the DB_URL in .env actually connects, and report the server version.

Run from the backend root:  python scripts/check_db.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from core.db import Engine  # noqa: E402

url = Engine.url
print(f"host={url.host} port={url.port} db={url.database} user={url.username}")

try:
    with Engine.connect() as conn:
        print("server:", conn.execute(text("select version()")).scalar_one()[:60])
        print("current_database:", conn.execute(text("select current_database()")).scalar_one())
        n = conn.execute(
            text(
                "select count(*) from information_schema.tables "
                "where table_schema = 'public'"
            )
        ).scalar_one()
        print("existing public tables:", n)
        ext = conn.execute(
            text("select count(*) from pg_extension where extname = 'pgcrypto'")
        ).scalar_one()
        print("pgcrypto installed:", bool(ext))
except Exception as exc:  # noqa: BLE001
    print("CONNECTION FAILED:", type(exc).__name__, str(exc)[:300])
    sys.exit(1)
