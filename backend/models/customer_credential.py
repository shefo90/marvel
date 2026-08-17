"""Optional shopper login.

Credentials attach to a ``customers`` row — they do not create a staff ``users``
row. A shopper who never registers simply has no credential.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base
from models.mixins import TimestampMixin


class CustomerCredential(Base, TimestampMixin):
    __tablename__ = "customer_credential"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    password_hash = mapped_column(String(255), nullable=False)
    password_changed_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count = mapped_column(Integer, nullable=False, server_default="0")
    locked_until = mapped_column(DateTime(timezone=True), nullable=True)
    is_active = mapped_column(Boolean, nullable=False, server_default="true")

    customer = relationship("Customer", back_populates="credential")

    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_credential_customer"),
        CheckConstraint(
            "failed_login_count >= 0", name="ck_customer_credential_failed_count"
        ),
    )
