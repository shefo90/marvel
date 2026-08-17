"""An anonymous browser identity.

The anchor that lets touches recorded before any email/phone exists be stitched
to a customer later. Section 4: "Do not depend on cookies alone" — this row is
server-side, so the history survives cookie loss once a cart or order attaches
to it.
"""

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class AttributionVisitor(Base):
    __tablename__ = "attribution_visitors"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Opaque first-party token issued on first landing. Not PII.
    visitor_token = mapped_column(String(64), nullable=False)
    # Section 4 GA context. Kept here so server events can be associated and
    # deduplicated (section 6's Measurement Protocol requirement).
    ga_client_id = mapped_column(String(64), nullable=True)
    first_seen_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    first_landing_page = mapped_column(Text, nullable=True)
    first_referrer = mapped_column(Text, nullable=True)
    user_agent = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    touches = relationship("AttributionTouch", back_populates="visitor")

    __table_args__ = (
        UniqueConstraint("visitor_token", name="uq_attribution_visitors_token"),
        Index("ix_attribution_visitors_ga_client_id", "ga_client_id"),
        Index("ix_attribution_visitors_last_seen_at", "last_seen_at"),
    )
