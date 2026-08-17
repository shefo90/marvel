"""Shopper refresh tokens.

Same rotation contract as the staff table, kept separate so revoking every
shopper session never touches staff sessions.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class CustomerRefreshToken(Base):
    __tablename__ = "customer_refresh_token"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    token_hash = mapped_column(String(64), nullable=False)
    jti = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    revoked = mapped_column(Boolean, nullable=False, server_default="false")
    revoked_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer = relationship("Customer", back_populates="refresh_tokens")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_customer_refresh_token_hash"),
        UniqueConstraint("jti", name="uq_customer_refresh_token_jti"),
        CheckConstraint(
            "(revoked = false AND revoked_at IS NULL) "
            "OR (revoked = true AND revoked_at IS NOT NULL)",
            name="ck_customer_refresh_token_revoked",
        ),
        Index("ix_customer_refresh_token_customer_id", "customer_id"),
        # Retention/purge job (section 12).
        Index("ix_customer_refresh_token_expires_at", "expires_at"),
    )
