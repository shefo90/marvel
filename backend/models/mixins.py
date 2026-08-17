"""Shared declarative mixins.

Not tables. Column definitions shared across the translation tables live here so
the five concrete translation models stay identical in shape without a
polymorphic table (design section 6.1).
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import declared_attr, mapped_column

# Slug format — expressed as a DENYLIST, deliberately.
#
# The obvious allowlist, ``slug ~ '^[[:alnum:]]+(-[[:alnum:]]+)*$'``, is wrong
# here. ``slug`` is COLLATE "C" (so Arabic compares byte-exactly and the unique
# index stays predictable), and under the C collation POSIX character classes
# are ASCII-only — so ``[[:alnum:]]`` rejects every Arabic letter. The failure is
# invisible in testing unless you compare against the *column*, because a bound
# parameter uses the database default collation instead.
#
# Denying specific ASCII characters works identically under every collation:
# the denied sets are pure ASCII, and Arabic passes by not being in them.
SLUG_FORMAT = (
    "slug = lower(slug) "
    "AND length(slug) > 0 "
    "AND slug !~ '[[:space:]]' "
    "AND slug !~ '[A-Z]' "
    "AND slug !~ '[!\"#$%&''()*+,./:;<=>?@[\\\\\\]^`{|}~]' "
    "AND slug NOT LIKE '-%' "
    "AND slug NOT LIKE '%-' "
    "AND slug NOT LIKE '%--%'"
)

# Invisible bidi/joiner guard. LRM/RLM, the embedding+override set, isolates,
# ZWJ/ZWNJ and tatweel survive copy-paste from Word and Photoshop and turn two
# visually identical slugs into two crawlable URLs (design section 6.4).
# Postgres regex has no \u escape, so the class is built with chr().
INVISIBLES = (
    "chr(1600)||chr(8203)||chr(8204)||chr(8205)||chr(8206)||chr(8207)||"
    "chr(8234)||chr(8235)||chr(8236)||chr(8237)||chr(8238)||"
    "chr(8294)||chr(8295)||chr(8296)||chr(8297)"
)
NO_INVISIBLES = f"slug !~ ('[' || {INVISIBLES} || ']')"


class TimestampMixin:
    @declared_attr
    def created_at(cls):
        return mapped_column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )

    @declared_attr
    def updated_at(cls):
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )


class SeoMixin:
    """Section 8A's CMS/admin field set for an indexable template.

    Lives on the base row for locale-independent policy and is repeated on
    translation rows for the per-locale text.
    """

    @declared_attr
    def seo_title(cls):
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def meta_description(cls):
        return mapped_column(String(320), nullable=True)

    @declared_attr
    def is_indexable(cls):
        return mapped_column(Boolean, nullable=False, server_default="true")

    @declared_attr
    def canonical_url_override(cls):
        return mapped_column(String(500), nullable=True)

    @declared_attr
    def og_title(cls):
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def og_description(cls):
        return mapped_column(String(500), nullable=True)

    @declared_attr
    def og_image_url(cls):
        return mapped_column(String(500), nullable=True)

    @declared_attr
    def content_updated_at(cls):
        return mapped_column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )


class TranslationMixin(TimestampMixin):
    """Per-locale content for one catalog entity.

    ``is_complete`` is a generated column, so hreflang cluster membership and
    sitemap eligibility are computed by the database rather than trusted to
    application code (design section 6.2).
    """

    @declared_attr
    def locale(cls):
        return mapped_column(
            String(5),
            ForeignKey("locales.code", onupdate="CASCADE"),
            nullable=False,
        )

    @declared_attr
    def title(cls):
        return mapped_column(Text, nullable=False)

    @declared_attr
    def description(cls):
        return mapped_column(Text, nullable=True)

    @declared_attr
    def slug(cls):
        # COLLATE "C" so Arabic strings compare byte-exactly rather than under a
        # locale-aware collation, keeping the unique index predictable.
        return mapped_column(String(200, collation="C"), nullable=False)

    @declared_attr
    def seo_title(cls):
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def meta_description(cls):
        return mapped_column(String(320), nullable=True)

    @declared_attr
    def og_title(cls):
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def og_description(cls):
        return mapped_column(String(500), nullable=True)

    @declared_attr
    def og_image_url(cls):
        return mapped_column(Text, nullable=True)

    @declared_attr
    def image_alt(cls):
        return mapped_column(Text, nullable=True)

    @declared_attr
    def robots_index(cls):
        return mapped_column(Boolean, nullable=False, server_default="true")

    @declared_attr
    def canonical_override(cls):
        return mapped_column(Text, nullable=True)

    @declared_attr
    def is_published(cls):
        return mapped_column(Boolean, nullable=False, server_default="false")

    @declared_attr
    def is_complete(cls):
        return mapped_column(
            Boolean,
            Computed(
                "(description IS NOT NULL AND btrim(description) <> '' "
                "AND meta_description IS NOT NULL AND btrim(meta_description) <> '')",
                persisted=True,
            ),
            nullable=False,
        )

    @declared_attr
    def translation_source(cls):
        return mapped_column(String(16), nullable=False, server_default="human")

    @declared_attr
    def published_at(cls):
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def content_updated_at(cls):
        return mapped_column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )


def translation_table_args(table: str, owner_col: str) -> tuple:
    """Named constraints + indexes every translation table shares."""
    return (
        UniqueConstraint("locale", "slug", name=f"uq_{table}_locale_slug"),
        UniqueConstraint(owner_col, "locale", name=f"uq_{table}_owner_locale"),
        CheckConstraint(SLUG_FORMAT, name=f"ck_{table}_slug_format"),
        CheckConstraint(NO_INVISIBLES, name=f"ck_{table}_slug_no_invisibles"),
        CheckConstraint(
            "is_published = false OR (title IS NOT NULL AND description IS NOT NULL "
            "AND meta_description IS NOT NULL)",
            name=f"ck_{table}_published_requires_content",
        ),
        CheckConstraint(
            "translation_source IN ('human','machine','fallback_en')",
            name=f"ck_{table}_source",
        ),
        Index(
            f"ix_{table}_sitemap",
            "locale",
            "content_updated_at",
            postgresql_where=text(
                "is_published AND robots_index AND is_complete "
                "AND canonical_override IS NULL"
            ),
        ),
        Index(
            f"ix_{table}_needs_work",
            "locale",
            postgresql_where=text("NOT is_complete OR NOT is_published"),
        ),
    )
