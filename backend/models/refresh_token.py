"""Staff refresh tokens.

The token is stored **hashed**, never in plaintext. Rotation looks the row up by
``jti``; a missing, revoked or expired row is rejected.
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash = mapped_column(String(64), nullable=False)
    jti = mapped_column(UUID(as_uuid=True), nullable=False)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    revoked = mapped_column(Boolean, nullable=False, server_default="false")
    revoked_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("User", back_populates="refresh_tokens")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
        UniqueConstraint("jti", name="uq_refresh_token_jti"),
        CheckConstraint(
            "(revoked = false AND revoked_at IS NULL) "
            "OR (revoked = true AND revoked_at IS NOT NULL)",
            name="ck_refresh_token_revoked",
        ),
        Index("ix_refresh_token_user_id", "user_id"),
        Index("ix_refresh_token_expires_at", "expires_at"),
    )
