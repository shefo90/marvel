"""Slug normalization and rename redirects.

The translation slug CHECK is a denylist, not an allowlist (migration 0003):
under COLLATE "C" the POSIX class [[:alnum:]] is ASCII-only, so an allowlist
rejects every Arabic slug. Normalization here mirrors that denylist exactly —
anything the constraint forbids is removed before the value reaches the column.
"""

import re
import unicodedata

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


def record_slug_change(
    db, *, locale: str, old_slug: str, product_id: int, actor_id: int | None
) -> None:
    """Write a 301 from the retired path.

    Entity-targeted rather than path-targeted: resolution is
    old path -> entity -> that entity's *current* slug, so renaming A->B->C
    still yields exactly one hop instead of a chain. ck_url_redirects_single_target
    requires exactly one of entity_id / to_path, so to_path stays NULL.
    """
    from_path = f"/{locale}/products/{old_slug}"
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
