import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from core.db import Engine  # noqa: E402

SLUGS = ["احذية", "صنادل", "صندل-جلد-بحزام", "اصدار-الصيف", "sandals"]

with Engine.connect() as c:
    src = c.execute(
        text(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conname = 'ck_category_translations_slug_format'"
        )
    ).scalar()
    print("constraint:", src, "\n")

    for s in SLUGS:
        row = c.execute(
            text(
                "select :s = lower(:s) as is_lower, "
                "(:s ~ '^[[:alnum:]]+(-[[:alnum:]]+)*$') as matches_format, "
                "length(:s) as chars, octet_length(:s) as bytes"
            ),
            {"s": s},
        ).one()
        print(f"{s!r:34} lower={row[0]} format={row[1]} chars={row[2]} bytes={row[3]}")
        if not row[1]:
            for i, ch in enumerate(s):
                ok = c.execute(
                    text("select :ch ~ '^[[:alnum:]]$'"), {"ch": ch}
                ).scalar()
                if not ok and ch != "-":
                    print(f"    offending char {i}: {ch!r} U+{ord(ch):04X}")
