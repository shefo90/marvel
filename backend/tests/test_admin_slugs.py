"""Slug rules and rename redirects.

Migration 0003 made the translation slug CHECK a *denylist* because
"[[:alnum:]]" is ASCII-only under COLLATE "C" and rejected every Arabic slug.
These tests defend that: Arabic must survive normalization intact.
"""

import pytest

from repositories.admin_slugs import normalize_translation_slug


def test_arabic_slug_survives_normalization():
    assert normalize_translation_slug("صندل جلد") == "صندل-جلد"


def test_spaces_become_single_hyphens():
    assert normalize_translation_slug("  suede   sandal  ") == "suede-sandal"


def test_uppercase_is_lowered():
    assert normalize_translation_slug("Suede Sandal") == "suede-sandal"


def test_punctuation_is_stripped():
    assert normalize_translation_slug("suede/sandal!") == "suedesandal"


def test_invisible_characters_are_removed():
    """Tatweel and the bidi marks are in the CHECK's denylist."""
    assert normalize_translation_slug("صنـدل") == "صندل"


def test_blank_slug_is_rejected():
    with pytest.raises(ValueError):
        normalize_translation_slug("   ")
