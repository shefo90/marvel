"""Create the first admin staff account.

Staff registration is admin-gated, so the very first admin cannot be created
through the API. This is the out-of-band path, and it is the only caller of
``create_staff_user`` outside the gated endpoint.

    python scripts/bootstrap_admin.py <email> <password> "<full name>"

Idempotent: re-running with an existing email reports it and exits 0.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from core.db import SessionLocal  # noqa: E402
from core.enums import StaffRole  # noqa: E402
from repositories.register import create_staff_user  # noqa: E402


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    email, password, full_name = sys.argv[1], sys.argv[2], sys.argv[3]
    db = SessionLocal()
    try:
        user = create_staff_user(
            db,
            email=email,
            password=password,
            full_name=full_name,
            role=StaffRole.admin.value,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            print(f"admin already exists: {email}")
            return 0
        print(f"failed: {exc.detail}")
        return 1
    finally:
        db.close()

    print(f"created admin id={user.id} email={user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
