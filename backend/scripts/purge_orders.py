"""Clear test orders out of the development database.

``test_cart_and_orders.py`` places real orders over HTTP, and until the purge
fixture in ``tests/conftest.py`` existed nothing removed them. They had built up
to over a thousand rows -- enough to make the admin order queue useless for
looking at anything real, and enough to skew any query anyone writes against
this database while developing.

The fixture stops the bleeding for new runs. This clears what is already there.

**Refuses to touch anything but this machine's development database.** An order
is the record of something that happened to a shopper's money; a script that
deletes them in bulk has no business being runnable anywhere else. It checks the
host in DATABASE_URL and stops if it is not local.

Dry run by default -- it prints what it would delete and exits. Deleting needs
``--yes``, spelled out, because there is no undo:

    python scripts/purge_orders.py                  # show me
    python scripts/purge_orders.py --yes            # do it
    python scripts/purge_orders.py --keep 50 --yes  # keep the 50 newest
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from core.db import Engine, SessionLocal  # noqa: E402
from models.orders import Order  # noqa: E402
from repositories.maintenance import delete_orders  # noqa: E402

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _refuse_if_not_local() -> str:
    """Stop unless the engine is pointed at this machine.

    Read off ``Engine.url`` rather than an environment variable, so the check
    describes the connection that will actually be used. A first draft of this
    consulted ``DATABASE_URL``, which this project does not set -- the variable
    is ``DB_URL`` -- and so the guard silently passed on every input, which is
    the one behaviour a safety check must never have.

    A missing host is refused rather than assumed local. Failing closed costs an
    explicit ``--host-ok`` in an unusual setup; failing open costs a production
    order table.
    """
    host = (Engine.url.host or "").lower()
    if host not in LOCAL_HOSTS:
        sys.exit(
            f"refusing to run against host {host or '(none)'!r}: this script "
            "only purges a local development database"
        )
    return host


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", type=int, default=0,
        help="keep this many of the newest orders (default: keep none)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="actually delete; without it this is a dry run",
    )
    args = parser.parse_args()

    host = _refuse_if_not_local()
    print(f"database: {Engine.url.database} on {host}:{Engine.url.port}")

    db = SessionLocal()
    try:
        total = db.execute(select(func.count()).select_from(Order)).scalar_one()
        doomed = db.execute(
            select(Order.id).order_by(Order.id.desc()).offset(args.keep)
        ).scalars().all()

        print(f"{total} orders present, {len(doomed)} would be deleted", end="")
        print(f", keeping the {args.keep} newest" if args.keep else "")

        if not doomed:
            return
        if not args.yes:
            print("dry run — pass --yes to delete")
            return

        removed = delete_orders(db, doomed)
        db.commit()
        print(f"deleted {removed}; {total - removed} remain")
    finally:
        db.close()


if __name__ == "__main__":
    main()
