"""search — Arabic-aware folding, and the two indexes it feeds

Open question 1 from 2026-08-17, closed: alef/hamza/taa-marbuta folding with
diacritics and tatweel stripped, applied *before* tokenization.

**Postgres's own ``arabic`` config already does most of this, and its gaps are
the reason the folding still has to exist.** Measured on this database:

    to_tsvector('arabic', 'حِذَاء')  -> 'حذاء'    diacritics: handled
    to_tsvector('arabic', 'حــذاء')  -> 'حذاء'    tatweel: handled
    to_tsvector('arabic', 'حذآء')    -> 'حذاء'    alef madda: handled

so far so good. But it is inconsistent in two places that decide whether a real
shopper finds anything:

    'مقهى'    -> 'مقه'      but  'مقهي'    -> 'مقهي'     <- do not match
    'الأحذية' -> 'احذ'      but  'الاحذيه' -> 'احذيه'    <- do not match

The second pair is the common case, not the exotic one: ``الاحذيه`` is how the
word is typed by someone not reaching for hamza on a phone keyboard. Left
alone, that shopper searches the shop's main category and is told there is
nothing. Folding first makes all seven variant pairs in tests/test_search.py
converge on one token.

**Why a generated column rather than normalizing in the repository.** The one
thing a search index cannot survive is the write path and the query path
disagreeing about normalization. Doing it in application code means two call
sites that must be changed together forever, and the failure is silent -- no
error, just results that quietly stop matching. A generated column is computed
by the database from the row itself, so it cannot drift from the text it
describes, and the query side calls the same ``marvel_fold`` function.

The cost is a real one and worth stating: **changing ``marvel_fold`` later will
not recompute stored values.** Postgres does not re-evaluate generated columns
on function replacement. Any future edit to the folding rules has to be a
migration that rewrites the table (``ALTER TABLE ... ALTER COLUMN ... DROP
EXPRESSION`` and re-add, or a plain table rewrite), not a ``CREATE OR REPLACE``.

**Two indexes because they answer different questions.** The tsvector handles
whole words with stemming, which is what makes "sandals" find "Sandal" in
English and what makes the Arabic stemmer useful at all. The trigram index
handles prefixes and typos -- "sanda", "sandel" -- which a tsvector cannot.
Neither subsumes the other.

The tsvector is locale-aware: ``arabic`` for Arabic rows, ``english`` for the
rest. One config for both would mean English never stems -- measured, the
arabic config leaves "sandals" as "sandals" -- so an English shopper's plural
would miss a singular title.

Revision ID: 0007_search
Revises: 0006_jobs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_search"
down_revision: Union[str, None] = "0006_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 15 characters in, 6 out. translate() deletes any source character with no
# counterpart, which is exactly the wanted behaviour for tatweel and the eight
# harakat -- they vanish rather than becoming spaces that split a word in two.
#
#   أ إ آ ٱ -> ا     the alef family, including madda and the wasla
#   ى       -> ي     alef maqsura, which the stemmer treats inconsistently
#   ة       -> ه     taa marbuta
#   ـ       -> ''    tatweel, a decorative stretch with no meaning
#   ًٌٍَُِّْ  -> ''    the harakat
FOLD_BODY = """
    SELECT translate(
        lower(coalesce(t, '')),
        'أإآٱىةـًٌٍَُِّْ',
        'اااايه'
    )
"""


def upgrade() -> None:
    # Prefix and typo tolerance. unaccent is not needed: it does not touch
    # Arabic letter forms, which is the entire problem here.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION marvel_fold(t text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        RETURNS NULL ON NULL INPUT
        AS $${FOLD_BODY}$$
        """
    )

    op.execute(
        """
        ALTER TABLE product_translations
        ADD COLUMN search_text text
        GENERATED ALWAYS AS (
            marvel_fold(coalesce(title, '') || ' ' || coalesce(description, ''))
        ) STORED
        """
    )

    op.execute(
        """
        ALTER TABLE product_translations
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            CASE WHEN locale = 'ar'
                THEN to_tsvector('arabic',
                     marvel_fold(coalesce(title, '') || ' ' || coalesce(description, '')))
                ELSE to_tsvector('english',
                     marvel_fold(coalesce(title, '') || ' ' || coalesce(description, '')))
            END
        ) STORED
        """
    )

    op.execute(
        "CREATE INDEX ix_product_translations_search_vector "
        "ON product_translations USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_product_translations_search_trgm "
        "ON product_translations USING gin (search_text gin_trgm_ops)"
    )

    # Brand lives on products, and a generated column cannot reach another
    # table, so it gets an expression index instead. Shoppers search by brand
    # more than by description.
    op.execute(
        "CREATE INDEX ix_products_brand_trgm "
        "ON products USING gin (marvel_fold(brand) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_product_translations_search_trgm")
    op.execute("DROP INDEX IF EXISTS ix_product_translations_search_vector")
    op.execute("ALTER TABLE product_translations DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE product_translations DROP COLUMN IF EXISTS search_text")
    # Dropped after the columns that depend on it, or Postgres refuses.
    op.execute("DROP FUNCTION IF EXISTS marvel_fold(text)")
    # pg_trgm is left installed: other things may come to rely on it, and
    # dropping an extension is not this migration's business to undo.
