"""The immutable per-order attribution snapshot.

Required by sections 3, 4, 9 and 16. Values are **copied** at order creation and
never joined at read time, so the snapshot survives touch-row purges, campaign
renames and customer identity merges.

Section 4 calls this the channel-neutral object that future adapters must
*extend* rather than replace with a per-platform table. Extension means either a
new namespaced key in ``extras`` or an additive migration — never a second
attribution table.

Section 15's acceptance test — "A payment-gateway redirect does not overwrite
the original source/medium or detach the order from its attribution snapshot" —
is satisfied structurally: ``order_id`` is the primary key, so there is exactly
one snapshot per order and no surrogate key to accidentally duplicate, and
nothing in the payment path writes here.
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


class OrderAttribution(Base):
    __tablename__ = "order_attributions"

    order_id = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )

    # --- Section 4 order snapshot: first and last touch, stored separately -
    first_touch_at = mapped_column(DateTime(timezone=True), nullable=True)
    first_touch_source = mapped_column(String(255), nullable=True)
    first_touch_medium = mapped_column(String(255), nullable=True)
    first_touch_campaign = mapped_column(String(255), nullable=True)
    first_touch_channel_group = mapped_column(String(64), nullable=True)
    first_touch_landing_page = mapped_column(Text, nullable=True)

    last_touch_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_touch_source = mapped_column(String(255), nullable=True)
    last_touch_medium = mapped_column(String(255), nullable=True)
    last_touch_campaign = mapped_column(String(255), nullable=True)
    last_touch_channel_group = mapped_column(String(64), nullable=True)
    last_touch_landing_page = mapped_column(Text, nullable=True)

    # --- UTM at conversion ------------------------------------------------
    utm_source = mapped_column(String(255), nullable=True)
    utm_medium = mapped_column(String(255), nullable=True)
    utm_campaign = mapped_column(String(255), nullable=True)
    utm_content = mapped_column(String(255), nullable=True)
    utm_term = mapped_column(String(255), nullable=True)
    utm_id = mapped_column(String(255), nullable=True)

    # --- Google. Retained for offline/Delivered conversion upload (section 6)
    gclid = mapped_column(String(255), nullable=True)
    gbraid = mapped_column(String(255), nullable=True)
    wbraid = mapped_column(String(255), nullable=True)

    # --- Meta -------------------------------------------------------------
    fbclid = mapped_column(String(255), nullable=True)
    fbp = mapped_column(String(255), nullable=True)
    fbc = mapped_column(String(255), nullable=True)

    # --- GA association for Measurement Protocol (section 6) --------------
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
    consent_state = mapped_column(JSONB, nullable=True)
    visitor_token = mapped_column(String(64), nullable=True)

    # --- Channels not yet enabled (TikTok, Snap, Microsoft, Pinterest) ----
    extras = mapped_column(JSONB, nullable=False, server_default="{}")

    snapshot_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order = relationship("Order", back_populates="attribution")

    __table_args__ = (
        Index("ix_order_attributions_gclid", "gclid"),
        Index(
            "ix_order_attributions_first_touch",
            "first_touch_source",
            "first_touch_campaign",
        ),
        Index(
            "ix_order_attributions_last_touch",
            "last_touch_source",
            "last_touch_campaign",
        ),
        Index("ix_order_attributions_extras", "extras", postgresql_using="gin"),
    )
