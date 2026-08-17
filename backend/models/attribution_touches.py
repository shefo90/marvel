"""One row per acquisition touch — section 4's channel-neutral schema.

Storage strategy (design section 2): typed, indexed columns for the stable core
that BI actually groups by, plus a JSONB ``extras`` for channels that are not
enabled yet.

TikTok and Snap identifiers deliberately live in ``extras`` rather than as typed
columns. Section 7 describes both as optional, "where the channel is enabled and
permitted" — promoting them to columns before the channel exists is dead weight,
and section 4 explicitly says new adapters must *extend* this schema rather than
invent a separate source of truth. Promoting a key from ``extras`` to a column
when a channel goes live is an ordinary migration.
"""

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class AttributionTouch(Base):
    __tablename__ = "attribution_touches"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    visitor_id = mapped_column(
        BigInteger,
        ForeignKey("attribution_visitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- UTM -------------------------------------------------------------
    utm_source = mapped_column(String(255), nullable=True)
    utm_medium = mapped_column(String(255), nullable=True)
    utm_campaign = mapped_column(String(255), nullable=True)
    utm_content = mapped_column(String(255), nullable=True)
    utm_term = mapped_column(String(255), nullable=True)
    utm_id = mapped_column(String(255), nullable=True)

    # --- Google click IDs. Auto-tagging is enabled, so these must survive. --
    gclid = mapped_column(String(255), nullable=True)
    gbraid = mapped_column(String(255), nullable=True)
    wbraid = mapped_column(String(255), nullable=True)

    # --- Meta -------------------------------------------------------------
    fbclid = mapped_column(String(255), nullable=True)
    fbp = mapped_column(String(255), nullable=True)
    fbc = mapped_column(String(255), nullable=True)

    # --- GA context -------------------------------------------------------
    ga_client_id = mapped_column(String(64), nullable=True)
    ga_session_id = mapped_column(String(64), nullable=True)

    # --- Partner / owned --------------------------------------------------
    affiliate_id = mapped_column(String(128), nullable=True)
    referral_code = mapped_column(String(128), nullable=True)
    coupon_code = mapped_column(String(64), nullable=True)

    # --- Context ----------------------------------------------------------
    landing_page = mapped_column(Text, nullable=True)
    referrer = mapped_column(Text, nullable=True)
    locale = mapped_column(String(5), nullable=True)
    # Section 12: the consent state in force when this touch was recorded.
    consent_state = mapped_column(JSONB, nullable=True)

    # --- Derived channel grouping ----------------------------------------
    source = mapped_column(String(255), nullable=True)
    medium = mapped_column(String(255), nullable=True)
    campaign = mapped_column(String(255), nullable=True)
    channel_group = mapped_column(String(64), nullable=True)

    # --- Not-yet-enabled channels (TikTok ttclid/_ttp, Snap sc_click_id/
    #     sc_cookie1, Microsoft msclkid, Pinterest, ...) -------------------
    extras = mapped_column(JSONB, nullable=False, server_default="{}")

    visitor = relationship("AttributionVisitor", back_populates="touches")

    __table_args__ = (
        Index("ix_attribution_touches_visitor_id", "visitor_id", "occurred_at"),
        Index("ix_attribution_touches_gclid", "gclid"),
        Index("ix_attribution_touches_occurred_at", "occurred_at"),
        Index("ix_attribution_touches_campaign", "source", "medium", "campaign"),
        Index("ix_attribution_touches_extras", "extras", postgresql_using="gin"),
    )
