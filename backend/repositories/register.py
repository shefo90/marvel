"""Account creation — staff users and shopper customers.

Home of **guest resolution**, which the order repository needs at checkout time.
Resolution lives here rather than in ``services/`` because it is a database
read-then-write against ``customer_identity``, and ``services/`` imports nothing
from the app.

The pure **normalization** it depends on lives in ``services/identity.py`` and is
re-exported below. It must have exactly one implementation: registration and
checkout previously normalized phones differently (``201001234567`` versus
``+201001234567``), which resolved one shopper to two customers and silently
corrupted every section 11A lifetime aggregate.

Design section 11A: "Guest identity merging must use explicit, auditable rules."
The rule implemented here is exactly one rule, stated once:

    A normalized email or a normalized phone maps to at most one customer.
    Registration RESOLVES against that map before it creates anything.

The consequence that matters: a shopper who checked out as a guest last month
and registers today is the **same** ``customers`` row, so their order history,
lifetime aggregates and first-touch attribution survive the transition. Creating
a second row would silently fork the customer and understate every section 11A
lifetime metric from that day forward.
"""

import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import IdentitySource, IdentityType
from services import identity
from models.customer_credential import CustomerCredential
from models.customer_identity import CustomerIdentity
from models.customers import Customer
from models.users import User
from schema.register import customer_register_request, staff_register_request
from services.hash_password import hash_password
from services.role_access_level import LEVEL_ADMIN, set_access_level

# Egypt is the only market (design section 2), so phone normalization can assume
# a single country code. A local 01xxxxxxxxx and its international +2 01xxxxxxxxx
# form are the same human, and if they normalize differently the guest-merge rule
# above quietly stops working for anyone who typed their number the other way.
EG_COUNTRY_CODE = identity.EG_COUNTRY_CODE


# Re-exported from services.identity so this module keeps its old call sites.
# These MUST NOT be reimplemented here: registration and checkout previously had
# separate normalizers that disagreed on phone format, which split one shopper
# into two customers and corrupted the section 11A lifetime-value layer.
normalize_email = identity.normalize_email
normalize_phone = identity.normalize_phone
sha256_hex = identity.sha256_hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _follow_merges(db: Session, customer: Customer) -> Customer:
    """Walk a merged customer to its surviving row.

    ``customer_merge`` points losers at winners; an identity row left pointing at
    a merged customer must still resolve to the row that owns the history. The
    bound is defensive — a cycle is prevented by ``ck_customers_no_self_merge``
    plus the FK, but an unbounded loop here would be a hang, not an error.
    """
    seen = 0
    while customer.merged_into_customer_id is not None and seen < 10:
        successor = db.get(Customer, customer.merged_into_customer_id)
        if successor is None:
            break
        customer = successor
        seen += 1
    return customer


def _identity_row(
    db: Session, identity_type: IdentityType, value_normalized: str
) -> CustomerIdentity | None:
    return db.execute(
        select(CustomerIdentity).where(
            CustomerIdentity.identity_type == identity_type,
            CustomerIdentity.value_normalized == value_normalized,
        )
    ).scalar_one_or_none()


def _attach_identity(
    db: Session,
    customer: Customer,
    identity_type: IdentityType,
    value_normalized: str,
    source: IdentitySource,
) -> None:
    """Add a match key to a customer, respecting the one-primary-per-type index.

    ``uq_customer_identity_primary`` is a partial unique index over
    ``(customer_id, identity_type) WHERE is_primary``, so the flag is claimed
    only when the customer has no current primary of that type. The first
    email/phone we ever see for a customer is their primary; later ones are
    additional match keys, not replacements.
    """
    has_primary = (
        db.execute(
            select(CustomerIdentity.id).where(
                CustomerIdentity.customer_id == customer.id,
                CustomerIdentity.identity_type == identity_type,
                CustomerIdentity.is_primary.is_(True),
            )
        ).first()
        is not None
    )
    db.add(
        CustomerIdentity(
            customer_id=customer.id,
            identity_type=identity_type,
            value_normalized=value_normalized,
            value_sha256=sha256_hex(value_normalized),
            source=source,
            is_primary=not has_primary,
        )
    )
    db.flush()


def find_customer_by_identity(
    db: Session, *, email: str | None = None, phone: str | None = None
) -> Customer | None:
    """Read-only lookup through the ``customer_identity`` match keys.

    Login resolves through this table rather than through ``customers.email``:
    ``customers.email`` carries no unique constraint (a shopper may appear under
    a phone identity with no email at all), whereas
    ``uq_customer_identity_value`` guarantees at most one owner per normalized
    value. Querying the unconstrained column would be a
    ``MultipleResultsFound`` waiting to happen.
    """
    email_norm = normalize_email(email)
    phone_norm = normalize_phone(phone)
    row = None
    if email_norm:
        row = _identity_row(db, IdentityType.email, email_norm)
    if row is None and phone_norm:
        row = _identity_row(db, IdentityType.phone, phone_norm)
    if row is None:
        return None
    return _follow_merges(db, row.customer)


def resolve_customer(
    db: Session,
    *,
    email: str | None = None,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    source: IdentitySource = IdentitySource.order,
) -> Customer:
    """Find the customer these contact details belong to, or create one.

    **Does not commit.** Checkout resolves a customer inside the same
    transaction that writes the order, and a commit here would leave a customer
    row behind if the order then failed. The caller owns the transaction.

    When the email resolves to customer A and the phone to a *different*
    customer B, A wins and B's phone identity is left alone. Rehoming an
    identity is a genuine merge: it needs a ``customer_merge`` row, aggregate
    recomputation and an audit trail, none of which belong in a registration
    path. This is the documented S1 boundary, not an oversight.
    """
    email_norm = normalize_email(email)
    phone_norm = normalize_phone(phone)
    if email_norm is None and phone_norm is None:
        # ck_customers_contact_present would reject the row anyway; failing here
        # gives a usable message instead of an IntegrityError.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an email or a phone number is required",
        )

    by_email = _identity_row(db, IdentityType.email, email_norm) if email_norm else None
    by_phone = _identity_row(db, IdentityType.phone, phone_norm) if phone_norm else None

    matched = by_email or by_phone
    now = _now()

    if matched is None:
        customer = Customer(
            email=email_norm,
            phone=phone_norm,
            first_name=first_name,
            last_name=last_name,
        )
        db.add(customer)
        db.flush()
    else:
        matched.last_seen_at = now
        customer = _follow_merges(db, matched.customer)
        # Backfill only what is missing. A registration must never overwrite a
        # name or address handle the shopper already gave us.
        if customer.email is None and email_norm:
            customer.email = email_norm
        if customer.phone is None and phone_norm:
            customer.phone = phone_norm
        if customer.first_name is None and first_name:
            customer.first_name = first_name
        if customer.last_name is None and last_name:
            customer.last_name = last_name

    if email_norm and by_email is None:
        _attach_identity(db, customer, IdentityType.email, email_norm, source)
    if phone_norm and by_phone is None:
        _attach_identity(db, customer, IdentityType.phone, phone_norm, source)

    db.flush()
    return customer


def create_staff_user(
    db: Session, *, email: str, password: str, full_name: str, role: str
) -> User:
    """Create a staff account with **no authorization check**.

    This is the bootstrap/CLI entry point — it exists because the very first
    admin cannot be created through an admin-gated endpoint. Every HTTP path
    must go through :func:`register_staff` instead.
    """
    email_norm = normalize_email(email)
    if email_norm is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="email is required"
        )

    # Matched through lower() so the query uses uq_users_email, which is an
    # expression index on lower(email) — a plain equality could not use it, and
    # would also miss any row stored with different casing.
    existing = db.execute(
        select(User.id).where(func.lower(User.email) == email_norm)
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    user = User(
        email=email_norm,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # uq_users_email is on lower(email); a concurrent insert lands here.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )
    db.refresh(user)
    return user


def register_staff(
    db: Session, actor_claims: dict, payload: staff_register_request
) -> User:
    """Admin-gated staff registration (design section 7, acceptance item 8).

    The token's ``access_level`` claim is not trusted on its own. It was minted
    at login and stays valid until the access token expires, so an admin
    demoted or deactivated five minutes ago still carries an admin claim. The
    actor is re-read from the database and re-checked.
    """
    actor = db.get(User, actor_claims.get("id"))
    if actor is None or not actor.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid actor"
        )
    if set_access_level(actor) < LEVEL_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="staff registration requires an admin",
        )

    return create_staff_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role.value,
    )


def register_customer(db: Session, payload: customer_register_request) -> Customer:
    """Attach a login to a customer, resolving an existing guest first.

    Registration never creates a second ``customers`` row for someone we have
    already sold to — see this module's docstring. It only ever *adds* a
    credential to the resolved row.
    """
    customer = resolve_customer(
        db,
        email=payload.email,
        phone=payload.phone,
        first_name=payload.first_name,
        last_name=payload.last_name,
        source=IdentitySource.account,
    )

    if customer.credential is not None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    db.add(
        CustomerCredential(
            customer_id=customer.id, password_hash=hash_password(payload.password)
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # uq_customer_credential_customer / uq_customer_identity_value under a
        # concurrent double-submit.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )
    db.refresh(customer)
    return customer
