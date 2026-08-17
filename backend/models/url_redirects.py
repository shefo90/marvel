"""Per-locale redirect history — section 8A.

    "If a slug changes, keep redirect history and issue a real server-side 301
    to the new canonical URL."

Four separate designs proposed this table; this is the merged version (design
section 3.1).

Two properties matter:

* **Locale-scoped.** An Arabic slug changes independently of its English
  counterpart, so history is keyed on ``(locale, from_path_fold)``. A redirect
  may never cross locales.
* **Entity-targeted, not path-targeted.** Storing ``entity_type``/``entity_id``
  rather than a literal ``to_path`` means resolution is always
  old path -> entity -> that entity's *current* slug in that locale. Renaming
  A -> B -> C therefore still yields exactly one 301 hop and can never build a
  chain. A literal ``to_path`` is still allowed for redirects that do not point
  at a catalog entity.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class UrlRedirect(Base):
    __tablename__ = "url_redirects"

    id = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    locale = mapped_column(
        String(5), ForeignKey("locales.code", onupdate="CASCADE"), nullable=False
    )
    from_path = mapped_column(Text, nullable=False)
    # Normalization-folded copy, compared under COLLATE "C" so Arabic strings
    # match byte-exactly rather than under a locale-aware collation.
    from_path_fold = mapped_column(Text(collation="C"), nullable=False)

    entity_type = mapped_column(String(32), nullable=True)
    entity_id = mapped_column(BigInteger, nullable=True)
    to_path = mapped_column(Text, nullable=True)

    status_code = mapped_column(SmallInteger, nullable=False, server_default="301")
    reason = mapped_column(String(48), nullable=True)
    is_active = mapped_column(Boolean, nullable=False, server_default="true")
    hit_count = mapped_column(BigInteger, nullable=False, server_default="0")
    last_hit_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_by = relationship("User", back_populates="created_redirects")

    __table_args__ = (
        # The resolver's only lookup key: one target per retired path per locale.
        UniqueConstraint(
            "locale", "from_path_fold", name="uq_url_redirects_locale_from_fold"
        ),
        CheckConstraint(
            "status_code IN (301, 308, 410)", name="ck_url_redirects_status"
        ),
        # A 301/308 must have exactly one target definition; a 410 needs none.
        CheckConstraint(
            "(status_code = 410 AND to_path IS NULL AND entity_id IS NULL) "
            "OR (status_code <> 410 AND ((entity_id IS NOT NULL)::int + (to_path IS NOT NULL)::int = 1))",
            name="ck_url_redirects_single_target",
        ),
        CheckConstraint("from_path LIKE '/%'", name="ck_url_redirects_from_absolute"),
        CheckConstraint(
            "to_path IS NULL OR to_path <> from_path", name="ck_url_redirects_no_self_loop"
        ),
        # Forbids cross-locale redirects: a slug change must stay in its locale.
        CheckConstraint(
            "to_path IS NULL OR to_path LIKE '/' || locale || '/%'",
            name="ck_url_redirects_same_locale",
        ),
        CheckConstraint(
            "entity_type IS NULL OR entity_type IN ('product','category','collection')",
            name="ck_url_redirects_entity_type",
        ),
        Index("ix_url_redirects_entity", "entity_type", "entity_id"),
        Index("ix_url_redirects_gone", "status_code", postgresql_where=text("status_code = 410")),
    )
