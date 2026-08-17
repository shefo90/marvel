"""End-to-end smoke test of the auth surface against the live database.

Uses TestClient, so no server process is needed.
Run from the backend root:  python scripts/smoke_auth.py

Exercises both identity families (staff + shopper), the admin gate, refresh
rotation for both, and the section 11A guest-identity-merge rule: a guest
customer row created at checkout must be REUSED when that person registers.

Test rows are namespaced with a run id and removed at the end, so the script is
re-runnable against the same seeded database.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from core.config import ALGORITHM, SECRET_KEY  # noqa: E402
from core.db import SessionLocal  # noqa: E402
from core.enums import IdentitySource, StaffRole  # noqa: E402
from main import app  # noqa: E402
from models.customer_identity import CustomerIdentity  # noqa: E402
from models.customers import Customer  # noqa: E402
from models.refresh_token import RefreshToken  # noqa: E402
from models.users import User  # noqa: E402
from repositories.register import (  # noqa: E402
    create_staff_user,
    resolve_customer,
    sha256_hex,
)

client = TestClient(app)
FAILURES: list[str] = []
RUN = uuid.uuid4().hex[:8]

ADMIN_EMAIL = f"admin.{RUN}@pixi-smoke.dev"
SUPPORT_EMAIL = f"support.{RUN}@pixi-smoke.dev"
NEW_STAFF_EMAIL = f"catalog.{RUN}@pixi-smoke.dev"
GUEST_EMAIL = f"guest.{RUN}@shopper-smoke.dev"
# Digits only: the guest phone is compared against its own normalized form, and
# a hex run id would smuggle letters into the expectation.
GUEST_PHONE = "01" + str(uuid.uuid4().int)[:9]
FRESH_EMAIL = f"fresh.{RUN}@shopper-smoke.dev"
PASSWORD = "Correct-Horse-9"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def claims(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# --- fixtures -------------------------------------------------------------
db = SessionLocal()
admin = create_staff_user(
    db,
    email=ADMIN_EMAIL,
    password=PASSWORD,
    full_name="Smoke Admin",
    role=StaffRole.admin.value,
)
support = create_staff_user(
    db,
    email=SUPPORT_EMAIL,
    password=PASSWORD,
    full_name="Smoke Support",
    role=StaffRole.support.value,
)
# A guest who ordered without ever registering: a customers row with identities
# but no credential. This is what registration must resolve against.
guest = resolve_customer(
    db,
    email=GUEST_EMAIL,
    phone=GUEST_PHONE,
    first_name="Guest",
    source=IdentitySource.order,
)
guest_id = guest.id
db.commit()
admin_id, support_id = admin.id, support.id
db.close()
print(f"fixtures: admin={admin_id} support={support_id} guest_customer={guest_id}")

print("\nstaff login:")
r = client.post(f"/api/en/auth/staff/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
check("admin login 200", r.status_code == 200, r.text[:200])
admin_tokens = r.json()
check("returns access + refresh", bool(admin_tokens.get("access_token")) and bool(admin_tokens.get("refresh_token")))
check("no password hash in body", "password" not in r.text and "hash" not in r.text)
ac = claims(admin_tokens["access_token"])
check("sub is the email", ac["sub"] == ADMIN_EMAIL, str(ac.get("sub")))
check("carries id/email/role", ac["id"] == admin_id and ac["email"] == ADMIN_EMAIL and ac["role"] == "admin")
check("carries access_level 4", ac["access_level"] == 4, str(ac.get("access_level")))
check("scope is staff", ac["scope"] == "staff", str(ac.get("scope")))
check("wrong password 401", client.post("/api/en/auth/staff/login", json={"email": ADMIN_EMAIL, "password": "nope-nope-nope"}).status_code == 401)
check("unknown staff email 401", client.post("/api/en/auth/staff/login", json={"email": f"ghost.{RUN}@pixi-smoke.dev", "password": PASSWORD}).status_code == 401)
check("unknown locale 404", client.post("/api/fr/auth/staff/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}).status_code == 404)

print("\nrefresh token is stored hashed, never plaintext:")
db = SessionLocal()
row = db.execute(select(RefreshToken).where(RefreshToken.user_id == admin_id)).scalars().all()
check("exactly one refresh row", len(row) == 1, str(len(row)))
stored = row[0]
check("stored value is sha256 hex(64)", len(stored.token_hash) == 64 and stored.token_hash == sha256_hex(admin_tokens["refresh_token"]))
check("plaintext token is not in the table", db.execute(text("select count(*) from refresh_token where token_hash = :t"), {"t": admin_tokens["refresh_token"]}).scalar() == 0)
db.close()

print("\nadmin-gated staff registration:")
r = client.post(f"/api/en/auth/staff/register", json={"email": NEW_STAFF_EMAIL, "password": PASSWORD, "full_name": "New Catalog", "role": "catalog"})
check("no token 403 (HTTPBearer)", r.status_code == 403, str(r.status_code))
r = client.post(
    "/api/en/auth/staff/register",
    json={"email": NEW_STAFF_EMAIL, "password": PASSWORD, "full_name": "New Catalog", "role": "catalog"},
    headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
)
check("admin can register staff 201", r.status_code == 201, r.text[:200])
created = r.json() if r.status_code == 201 else {}
check("response has no password_hash", "password_hash" not in r.text)
check("role echoed", created.get("role") == "catalog", str(created.get("role")))

support_tokens = client.post("/api/en/auth/staff/login", json={"email": SUPPORT_EMAIL, "password": PASSWORD}).json()
r = client.post(
    "/api/en/auth/staff/register",
    json={"email": f"x.{RUN}@pixi-smoke.dev", "password": PASSWORD, "full_name": "X", "role": "support"},
    headers={"Authorization": f"Bearer {support_tokens['access_token']}"},
)
check("non-admin staff gets 403", r.status_code == 403, r.text[:200])

r = client.post(
    "/api/en/auth/staff/register",
    json={"email": NEW_STAFF_EMAIL, "password": PASSWORD, "full_name": "Dup", "role": "catalog"},
    headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
)
check("duplicate staff email 409", r.status_code == 409, str(r.status_code))

print("\nshopper registration reuses the guest customers row (section 11A):")
r = client.post(
    "/api/en/auth/register",
    json={"email": GUEST_EMAIL, "password": PASSWORD, "phone": "+20 " + GUEST_PHONE[1:], "last_name": "Shopper"},
)
check("register 201", r.status_code == 201, r.text[:300])
body = r.json() if r.status_code == 201 else {}
check("exposes public_id, not customers.id", "public_id" in body and "id" not in body, str(sorted(body)))
db = SessionLocal()
resolved = db.execute(select(Customer).where(Customer.public_id == uuid.UUID(body["public_id"]))).scalar_one()
check("SAME customer row as the guest — no duplicate", resolved.id == guest_id, f"{resolved.id} vs guest {guest_id}")
check("credential attached", resolved.credential is not None)
check("guest name preserved, not overwritten", resolved.first_name == "Guest", str(resolved.first_name))
check("missing last_name backfilled", resolved.last_name == "Shopper", str(resolved.last_name))
ids = db.execute(select(CustomerIdentity).where(CustomerIdentity.customer_id == guest_id)).scalars().all()
check("still exactly 2 identities (+20 form did not create a third)", len(ids) == 2, str([(i.identity_type.value, i.value_normalized) for i in ids]))
check("email identity is lowercased/trimmed", any(i.value_normalized == GUEST_EMAIL.lower() for i in ids))
# Canonical phone form is E.164 WITH the leading '+', defined once in
# services/identity.py. This assertion previously encoded register.py's
# digits-only form, which disagreed with checkout and split one shopper across
# two customer_identity rows.
check("phone identity is canonical E.164", any(i.value_normalized == "+20" + GUEST_PHONE[1:] for i in ids), str([i.value_normalized for i in ids]))
check("value_sha256 is 64 hex", all(len(i.value_sha256) == 64 for i in ids))
check("sha256 matches the normalized value", all(i.value_sha256 == sha256_hex(i.value_normalized) for i in ids))
db.close()

check("re-registering the same email 409", client.post("/api/en/auth/register", json={"email": GUEST_EMAIL, "password": PASSWORD}).status_code == 409)
check("short password 422", client.post("/api/en/auth/register", json={"email": FRESH_EMAIL, "password": "short"}).status_code == 422)

print("\nshopper login:")
r = client.post("/api/en/auth/register", json={"email": FRESH_EMAIL, "password": PASSWORD})
check("fresh shopper registers 201", r.status_code == 201, r.text[:200])
r = client.post("/api/en/auth/login", json={"email": FRESH_EMAIL.upper(), "password": PASSWORD})
check("login is case-insensitive on email", r.status_code == 200, r.text[:200])
cust_tokens = r.json()
cc = claims(cust_tokens["access_token"])
check("scope is customer", cc["scope"] == "customer", str(cc.get("scope")))
check("token carries public_id, NOT customers.id", "public_id" in cc and "id" not in cc, str(sorted(cc)))
check("wrong shopper password 401", client.post("/api/en/auth/login", json={"email": FRESH_EMAIL, "password": "wrong-wrong-1"}).status_code == 401)

print("\nscopes are not interchangeable:")
check(
    "shopper token rejected by staff endpoint",
    client.post("/api/en/auth/staff/register", json={"email": f"y.{RUN}@pixi-smoke.dev", "password": PASSWORD, "full_name": "Y", "role": "support"}, headers={"Authorization": f"Bearer {cust_tokens['access_token']}"}).status_code == 401,
)
check(
    "staff access token rejected as a refresh token",
    client.post("/api/en/auth/staff/refresh", headers={"Authorization": f"Bearer {admin_tokens['access_token']}"}).status_code == 401,
)

print("\nstaff refresh rotation:")
old_staff_refresh = admin_tokens["refresh_token"]
r = client.post("/api/en/auth/staff/refresh", headers={"Authorization": f"Bearer {old_staff_refresh}"})
check("rotation 200", r.status_code == 200, r.text[:200])
rotated = r.json()
check("returns a NEW access token", rotated["access_token"] != admin_tokens["access_token"])
check("returns a NEW refresh token", rotated["refresh_token"] != old_staff_refresh)
db = SessionLocal()
old_row = db.execute(select(RefreshToken).where(RefreshToken.jti == uuid.UUID(claims(old_staff_refresh)["jti"]))).scalar_one()
check("old row revoked = true", old_row.revoked is True)
check("old row revoked_at set (CHECK requires agreement)", old_row.revoked_at is not None)
new_row = db.execute(select(RefreshToken).where(RefreshToken.jti == uuid.UUID(claims(rotated["refresh_token"])["jti"]))).scalar_one()
check("new row persisted, hashed, not revoked", new_row.token_hash == sha256_hex(rotated["refresh_token"]) and not new_row.revoked)
db.close()
check("replaying the revoked refresh token 401", client.post("/api/en/auth/staff/refresh", headers={"Authorization": f"Bearer {old_staff_refresh}"}).status_code == 401)
r = client.post("/api/en/auth/staff/refresh", headers={"Authorization": f"Bearer {rotated['refresh_token']}"})
check("the new refresh token still works", r.status_code == 200, r.text[:200])
# The only staff refresh token still live after two rotations.
live_staff_refresh = r.json()["refresh_token"] if r.status_code == 200 else rotated["refresh_token"]

print("\nshopper refresh rotation:")
old_cust_refresh = cust_tokens["refresh_token"]
r = client.post("/api/en/auth/refresh", headers={"Authorization": f"Bearer {old_cust_refresh}"})
check("rotation 200", r.status_code == 200, r.text[:200])
cust_rotated = r.json()
# Only the refresh token is asserted to differ. ``create_access_token`` has
# second-resolution iat/exp and no jti, so a rotation landing in the same second
# as the login re-encodes byte-identical claims — a real property of the token
# service, not a rotation failure. The access token is checked for validity and
# scope instead.
check("new refresh token issued", cust_rotated["refresh_token"] != old_cust_refresh)
check("new access token is valid and customer-scoped", claims(cust_rotated["access_token"])["scope"] == "customer")
check("replay of the old one 401", client.post("/api/en/auth/refresh", headers={"Authorization": f"Bearer {old_cust_refresh}"}).status_code == 401)
check("staff refresh token rejected on the shopper path", client.post("/api/en/auth/refresh", headers={"Authorization": f"Bearer {live_staff_refresh}"}).status_code == 401)
check("forged jti (unknown row) 401", client.post("/api/en/auth/refresh", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401)

print("\nshopper lockout after repeated failures:")
for _ in range(5):
    client.post("/api/en/auth/login", json={"email": FRESH_EMAIL, "password": "wrong-wrong-1"})
r = client.post("/api/en/auth/login", json={"email": FRESH_EMAIL, "password": PASSWORD})
check("locked out with 403 even with the right password", r.status_code == 403, r.text[:200])

print("\ndeactivated staff cannot rotate:")
db = SessionLocal()
db.execute(text("update users set is_active = false where id = :i"), {"i": admin_id})
db.commit()
db.close()
r = client.post("/api/en/auth/staff/refresh", headers={"Authorization": f"Bearer {live_staff_refresh}"})
check("rotation by a deactivated user 403", r.status_code == 403, r.text[:200])

# --- cleanup --------------------------------------------------------------
db = SessionLocal()
db.execute(text("delete from users where email like :p"), {"p": f"%{RUN}@pixi-smoke.dev"})
db.execute(
    text(
        "delete from customers where id in ("
        " select customer_id from customer_identity where value_normalized like :e"
        ")"
    ),
    {"e": f"%{RUN}@shopper-smoke.dev"},
)
db.execute(text("delete from customers where id = :i"), {"i": guest_id})
db.commit()
remaining = db.execute(text("select count(*) from customers where id = :i"), {"i": guest_id}).scalar()
db.close()
print(f"\ncleanup: guest rows remaining = {remaining}")

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} -> {FAILURES}")
    sys.exit(1)
print("all auth smoke checks passed")
