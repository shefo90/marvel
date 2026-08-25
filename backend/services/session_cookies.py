"""Shopper session cookies, and the CSRF defence that cookie auth requires.

The storefront holds its access token in memory and its refresh token in an
httpOnly cookie. The admin and the cart use ``localStorage`` instead, and the
difference is deliberate rather than an inconsistency: the storefront is the
public surface, the one that renders merchandising copy and loads third-party
measurement, so it is where an XSS is most likely to land. An access token
stolen there expires in minutes; a refresh token stolen from ``localStorage`` is
an account for as long as the shopper does not notice.

**Why the cookie forces a CSRF story.** A bearer token in a header is immune to
CSRF for free — the browser never attaches it on its own. A cookie is attached
automatically to any request the browser is tricked into making, which is the
whole vulnerability. Two defences, layered:

1. ``SameSite=Lax`` — the browser withholds the cookie on cross-site POSTs. This
   is genuinely sufficient in current browsers and is the primary defence.
2. A double-submit token — a *readable* ``marvel_csrf`` cookie whose value must
   be echoed back in an ``X-CSRF-Token`` header. An attacker's page can cause
   the browser to send our cookies but cannot read them across origins, so it
   cannot construct the header.

The second exists because the first is a browser default, and a default is a
thing that can be relaxed by a policy, a quirks mode, or an embedded webview
somebody ships in two years. Defence in depth is the point.

**The CSRF cookie is deliberately readable by script**, which looks wrong beside
an httpOnly refresh cookie and is not. The page has to read it to echo it. Its
value is not a credential — on its own it authorises nothing — and its secrecy
from *other origins*, enforced by the same-origin policy, is the entire
mechanism.

``Secure`` is derived from the request scheme with an explicit ``COOKIE_SECURE``
override, for reasons written up on ``_secure`` -- the short version being that
a ``Secure`` cookie is never returned over plain HTTP, so defaulting it on
breaks local development and the test suite without raising anything.
"""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, Response, status

REFRESH_COOKIE = "marvel_refresh"
CSRF_COOKIE = "marvel_csrf"
CSRF_HEADER = "X-CSRF-Token"

# The refresh token's own lifetime, mirrored onto the cookie so the browser
# forgets it at the same moment the server stops honouring it.
REFRESH_MAX_AGE = 60 * 60 * 24 * 30

# Scoped to the API so the cookie is not attached to every image and stylesheet
# request the storefront makes.
COOKIE_PATH = "/api"


def _secure(request: Request) -> bool:
    """Whether to mark the cookies ``Secure``.

    Derived from the request scheme, with ``COOKIE_SECURE`` as an explicit
    override. The first draft of this defaulted to ``True`` unless an env var
    said otherwise, which is the instinct you are supposed to have and was
    wrong: a ``Secure`` cookie is not sent back over plain HTTP at all, so
    development on ``http://localhost`` and the whole test suite silently could
    not refresh a session. Nothing errored -- the cookie was set, then never
    returned -- which is the worst shape a security default can fail in.

    **Production must set ``COOKIE_SECURE=1``.** Behind a TLS-terminating proxy
    the application sees plain HTTP, so the derived answer is only right if
    uvicorn runs with ``--proxy-headers`` and the proxy sets
    ``X-Forwarded-Proto``. The override exists so that correctness there does
    not depend on remembering a uvicorn flag.
    """
    override = os.getenv("COOKIE_SECURE", "").lower()
    if override in ("1", "true", "yes"):
        return True
    if override in ("0", "false", "no"):
        return False
    return request.url.scheme == "https"


def issue_session(request: Request, response: Response, refresh_token: str) -> str:
    """Attach the refresh and CSRF cookies. Returns the CSRF value.

    The CSRF value is minted per session rather than per request: a per-request
    token would invalidate itself for any page with two requests in flight,
    which the storefront has on every page load.
    """
    csrf = secrets.token_urlsafe(32)

    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=REFRESH_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path=COOKIE_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=REFRESH_MAX_AGE,
        httponly=False,  # the page must read this to echo it; see the docstring
        samesite="lax",
        secure=_secure(request),
        path=COOKIE_PATH,
    )
    return csrf


def clear_session(response: Response) -> None:
    """Remove both cookies.

    The path must match the one they were set with or the browser deletes
    nothing and keeps sending the originals — a sign-out that appears to work
    and does not.
    """
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)


def require_refresh_cookie(request: Request) -> str:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="no session"
        )
    return token


def require_csrf(request: Request) -> None:
    """Double-submit check. Constant-time, and never trusts a missing value.

    Both halves must be present: an empty header matching an empty cookie is a
    request with no CSRF protection, not a request that passed the check.
    """
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed"
        )
