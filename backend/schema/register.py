"""Registration contracts — staff accounts and shopper accounts.

Zero logic. Pydantic models only.

Two things are deliberate here:

* **No password ever comes back out.** Neither response model carries
  ``password`` or ``password_hash``, so a careless ``response_model`` swap
  cannot leak one.
* **The shopper response exposes ``public_id``, not ``customers.id``.** Design
  section 4 pins ``customers.id`` as the internal, non-PII ``customer_id`` that
  is "never exposed to the browser". ``public_id`` is the opaque UUID that
  exists for exactly this purpose.

Passwords cap at 72 characters because bcrypt hashes only the first 72 *bytes*;
accepting more silently truncates and makes the extra characters decorative.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from core.enums import CustomerStatus, StaffRole


class staff_register_request(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=150)
    role: StaffRole


class staff_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: StaffRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class customer_register_request(BaseModel):
    """Phone is optional but load-bearing when present.

    A guest who checked out by phone alone is matched on it (design section 11A
    guest identity merging), so supplying it at registration is what reunites
    the shopper with their existing order history.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=32)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class customer_response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Section 4: the internal customers.id is deliberately absent.
    public_id: UUID
    status: CustomerStatus
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    orders_count: int = 0
    created_at: datetime
