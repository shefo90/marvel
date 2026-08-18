"""Slug normalization and rename redirects.

The translation slug CHECK is a denylist, not an allowlist (migration 0003):
under COLLATE "C" the POSIX class [[:alnum:]] is ASCII-only, so an allowlist
rejects every Arabic slug. Normalization here mirrors that denylist exactly —
anything the constraint forbids is removed before the value reaches the column.
"""

import re
import unicodedata

from sqlalchemy import select

from models.url_redirects import UrlRedirect

# Exactly the characters ck_*_slug_no_invisibles forbids.
_INVISIBLES = "".join(
    chr(c) for c in (0x0640, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
                     0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                     0x2066, 0x2067, 0x2068, 0x2069)
)
_PUNCT = re.compile(r"""[!"#$%&'()*+,./:;<=>?@\[\\\]^`{|}~]""")


def normalize_translation_slug(raw: str) -> str:
    """Fold a human-typed title into a slug the CHECK constraint accepts.

    Arabic text is preserved as real Arabic — the locked decision is that slugs
    are stored decoded and percent-encoded exactly once at render.
    """
    text = unicodedata.normalize("NFC", raw or "")
    text = text.translate({ord(c): None for c in _INVISIBLES})
    text = _PUNCT.sub("", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-").lower()
    if not text:
        raise ValueError("slug is empty after normalization")
    return text


def fold_path(path: str) -> str:
    """The comparison form stored in url_redirects.from_path_fold."""
    return unicodedata.normalize("NFC", path).lower()


def product_path(locale: str, slug: str) -> str:
    """The storefront path a product translation is served at.

    Provisional: no storefront exists yet to confirm the ``products`` segment.
    It is a function so S2 has one place to correct, rather than two string
    literals that can drift apart.
    """
    return f"/{locale}/products/{slug}"


def _redirect_from(db, locale: str, path: str) -> UrlRedirect | None:
    """The single row uq_url_redirects_locale_from_fold allows for this path."""
    return db.execute(
        select(UrlRedirect).where(
            UrlRedirect.locale == locale,
            UrlRedirect.from_path_fold == fold_path(path),
        )
    ).scalar_one_or_none()


def record_slug_change(
    db, *, locale: str, old_slug: str, product_id: int, actor_id: int | None
) -> None:
    """Write a 301 from the retired path.

    Entity-targeted rather than path-targeted: resolution is
    old path -> entity -> that entity's *current* slug, so renaming A->B->C
    still yields exactly one hop instead of a chain. ck_url_redirects_single_target
    requires exactly one of entity_id / to_path, so to_path stays NULL.

    Idempotent, because uq_url_redirects_locale_from_fold allows exactly one row
    per (locale, path) and a slug can be retired more than once: renaming
    a->b->a->b blind-inserted ``/ar/products/a`` twice and the second insert was
    an uncaught IntegrityError that lost the rename. A row that already exists
    for this path is re-pointed at the current entity and reactivated instead --
    which is also what makes it self-healing, since the entity that path belongs
    to may have changed since the row was written.
    """
    from_path = product_path(locale, old_slug)
    existing = _redirect_from(db, locale, from_path)
    if existing is None:
        db.add(
            UrlRedirect(
                locale=locale,
                from_path=from_path,
                from_path_fold=fold_path(from_path),
                entity_type="product",
                entity_id=product_id,
                to_path=None,
                status_code=301,
                reason="slug_change",
                is_active=True,
                created_by_user_id=actor_id,
            )
        )
        return

    # from_path itself is rewritten too: from_path_fold is the lower-cased
    # comparison form, so two differently-cased paths share one row and the
    # stored original should be the one actually retired this time.
    existing.from_path = from_path
    existing.entity_type = "product"
    existing.entity_id = product_id
    existing.to_path = None
    existing.status_code = 301
    existing.reason = "slug_change"
    existing.is_active = True
    existing.created_by_user_id = actor_id


def release_live_path(db, *, locale: str, slug: str) -> None:
    """Stop any redirect *from* a path that is being served again.

    Renaming a->b->a leaves ``/ar/products/a -> this product`` on file while the
    product lives at ``a`` once more: the resolver would 301 that URL to itself.
    The same row is equally wrong when a *different* product takes the freed
    slug -- uq_product_translations_locale_slug releases it as soon as the first
    product moves off -- because then it 301s a live URL to the wrong product.

    Deactivated rather than deleted: the history is the point of the table, and
    renaming back retires the path again through record_slug_change, which
    reactivates this same row.
    """
    row = _redirect_from(db, locale, product_path(locale, slug))
    if row is not None and row.is_active:
        row.is_active = False
