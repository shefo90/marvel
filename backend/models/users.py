"""Staff accounts.

Staff only — shoppers live in ``customers``. Keeping them apart stops the auth
model from tangling with the analytics customer master and avoids placeholder
user rows for guest orders (design section 2).
"""

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from core.enums import StaffRole
from models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    email = mapped_column(String(320), nullable=False)
    password_hash = mapped_column(String(255), nullable=False)
    full_name = mapped_column(String(150), nullable=False)
    role = mapped_column(SAEnum(StaffRole, native_enum=False, length=16), nullable=False)
    is_active = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at = mapped_column(DateTime(timezone=True), nullable=True)

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    customer_merges = relationship("CustomerMerge", back_populates="actor_user")
    created_redirects = relationship("UrlRedirect", back_populates="created_by")
    order_audit_entries = relationship("OrderAuditLog", back_populates="actor_user")

    __table_args__ = (
        # Case-insensitive login identity.
        Index("uq_users_email", text("lower(email)"), unique=True),
        # Enumerate active privileged accounts for access reviews (section 13).
        Index("ix_users_role", "role", postgresql_where=text("is_active")),
    )
