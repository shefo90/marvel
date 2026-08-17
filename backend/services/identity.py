"""Customer identity normalization — the single source of truth.

Stateless: no DB session, no models, no domain knowledge.

**Why this module exists.** ``register.py`` and ``order.py`` each grew their own
email/phone normalizers, and they disagreed: one produced ``201001234567`` and
the other ``+201001234567``. Same shopper, two ``customer_identity`` rows, two
``customers``. Nothing failed loudly — section 11A's new-vs-returning
classification and every lifetime-value aggregate would simply have been wrong,
and the split would only surface as unexplained duplicate customers months later.

Every caller must import from here. Do not add a second normalizer.

**Canonical phone form is E.164 with the leading ``+``.** That choice is
deliberate but not free: ad destinations disagree about hashing format — Google
Ads Enhanced Conversions wants E.164 with ``+``, Meta's CAPI wants bare digits.
Storing one unambiguous canonical form and letting each destination adapter
format at send time (S5) is the only way both stay correct. The stored
``value_sha256`` is therefore a *local* match key, NOT a value that can be
shipped to every platform unchanged.
"""

from __future__ import annotations

import hashlib
import re

EG_COUNTRY_CODE = "20"


def normalize_email(value: str | None) -> str | None:
    """Lowercase and trim. Nothing cleverer.

    Deliberately does NOT strip Gmail dots or ``+tag`` suffixes: those rules are
    provider-specific, and applying them would merge two people who really are
    distinct on any provider that treats the local part literally.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    """Egyptian numbers to E.164, e.g. ``+201001234567``.

    ``01001234567``, ``0100 123 4567``, ``+20 100 123 4567``, ``0020 100 123
    4567`` and ``201001234567`` all collapse to one identity. A number that does
    not look Egyptian keeps its digits rather than being guessed at, prefixed
    with ``+`` only when it already carried an international form.

    Single-market by design (design section 2), so this is intentionally not a
    general phone library.
    """
    if value is None:
        return None

    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None

    had_intl = raw.startswith("+") or digits.startswith("00")

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        # Local Egyptian form: 01xxxxxxxxx -> 201xxxxxxxxx
        digits = EG_COUNTRY_CODE + digits[1:]
        had_intl = True
    elif digits.startswith(EG_COUNTRY_CODE):
        had_intl = True

    return f"+{digits}" if had_intl else digits


def sha256_hex(value: str) -> str:
    """64 lowercase hex characters — the length ``customer_identity`` CHECKs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
