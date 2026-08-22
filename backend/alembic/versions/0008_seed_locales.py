"""locales — the two reference rows the application cannot start without

Found by deploying to a fresh database and watching every page 404.

``locales`` is a foreign-key target for every translation table, and
``valid_locale`` rejects any code not present in it. With the table empty, a
freshly migrated shop answers 404 to ``/api/en/products``, ``/api/ar/products``
and every catalogue route there is, while ``/health`` cheerfully returns 200 --
so the container reports itself healthy and the shop serves nothing.

**Reference data, not seed data, which is why it is a migration.** The seed
scripts in ``backend/scripts/`` create example products and a category tree:
things a real shop replaces. These two rows are not examples. Egypt, English and
Arabic is a locked decision (design section 6), the schema is built around
exactly these codes, and no deployment ever wants a different set. Leaving them
to a script means every fresh deployment is broken until somebody remembers to
run one, and the failure gives no hint of the cause.

Idempotent via ON CONFLICT: this may run against a development database that
already has both rows, and a data migration that explodes on re-entry is worse
than one that does nothing.

Revision ID: 0008_seed_locales
Revises: 0007_search
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_seed_locales"
down_revision: Union[str, None] = "0007_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO locales
            (code, hreflang, name_native, text_direction, is_default, is_active, sort_order)
        VALUES
            ('en', 'en', 'English',  'ltr', true,  true, 1),
            ('ar', 'ar', 'العربية', 'rtl', false, true, 2)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    # Deliberately not deleted. Every translation row in the database references
    # one of these, so removing them is either a foreign-key violation or, worse,
    # a cascade that takes the shop's entire content with it. Downgrading past
    # this migration leaves two rows behind, which is the harmless direction.
    pass
