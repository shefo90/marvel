"""Shopper sessions held in an httpOnly cookie rather than in localStorage.

The admin app and the cart both keep their tokens in ``localStorage``, and for
those two that is a defensible trade. This is the shopper-facing storefront: it
renders merchandising copy, runs third-party measurement, and is the widest XSS
surface in the project. A refresh token readable by script there is a long-lived
account credential that outlives the tab it was stolen from.

So the storefront gets its own session endpoints, and they differ from
``/auth/login`` in exactly one way that matters: **the refresh token never
appears in a response body.** It is set as an httpOnly, SameSite=Lax cookie the
page's own JavaScript cannot read. The access token still comes back in the body
and is held in memory only, where an XSS can use it while the tab is open but
cannot keep it.

The existing header-based ``/auth/login`` and ``/auth/refresh`` are untouched.
They are tested, the admin uses the staff pair, and adding a second way to do
something is safer than changing the contract of the first.

**Cookie authentication needs CSRF protection.** SameSite=Lax already stops a
cross-site form POST from carrying the cookie, but it is one browser default
away from being the only defence, so refresh also requires a double-submit
token: a readable ``marvel_csrf`` cookie whose value must be echoed in an
``X-CSRF-Token`` header. An attacker's page can cause the cookie to be sent but
cannot read it to construct the header.
"""

import uuid

import pytest

CSRF_COOKIE = "marvel_csrf"
REFRESH_COOKIE = "marvel_refresh"
PASSWORD = "Shopper-Pass-2026!"


@pytest.fixture(autouse=True)
def _isolate_cookies(client):
    """Empty the shared client's cookie jar around every test in this file.

    ``client`` is session-scoped, so it is one cookie jar for the entire run.
    These are the only tests that make the server set cookies, and without this
    a session established here would still be attached to requests made by
    every test that follows -- an authenticated visitor arriving in suites
    written to describe an anonymous one.
    """
    client.cookies.clear()
    yield
    client.cookies.clear()



@pytest.fixture
def shopper(client):
    """A registered shopper, removed afterwards.

    Registration commits, so this cannot ride on the rolled-back session
    fixtures. ``.local`` domains are rejected by the email validation, which is
    how an earlier session created an account that could never sign in.
    """
    email = f"shopper-{uuid.uuid4().hex[:10]}@example.com"
    created = client.post(
        "/api/en/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert created.status_code == 201, created.text

    yield email

    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from core.db import SessionLocal
    from models.customer_credential import CustomerCredential
    from models.customer_refresh_token import CustomerRefreshToken
    from models.customers import Customer

    db = SessionLocal()
    try:
        customer = db.execute(
            select(Customer).where(Customer.email == email)
        ).scalar_one_or_none()
        if customer is not None:
            # Core deletes in dependency order. Mixing ORM deletes with the
            # relationship cascades meant SQLAlchemy queued the same row twice
            # and warned when the second DELETE matched nothing -- noise that
            # makes a genuinely surprising warning easy to scroll past.
            db.execute(
                sa_delete(CustomerCredential).where(
                    CustomerCredential.customer_id == customer.id
                )
            )
            db.execute(
                sa_delete(CustomerRefreshToken).where(
                    CustomerRefreshToken.customer_id == customer.id
                )
            )
            db.flush()
            db.delete(customer)
        db.commit()
    finally:
        db.close()


def _login(client, email):
    return client.post(
        "/api/en/account/session", json={"email": email, "password": PASSWORD}
    )


def test_signing_in_returns_an_access_token(client, shopper):
    r = _login(client, shopper)

    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_signing_in_puts_no_refresh_token_in_the_body(client, shopper):
    """The whole point. A refresh token in the body is a refresh token the page
    can read, and therefore one an XSS can keep."""
    r = _login(client, shopper)

    # Asserting the status first: "the key is absent" is also true of a 404, so
    # without this the test would pass before the endpoint existed.
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()


def test_signing_in_sets_the_refresh_cookie_httponly(client, shopper):
    r = _login(client, shopper)

    cookie = r.cookies.get(REFRESH_COOKIE)
    assert cookie, "no refresh cookie was set"
    header = r.headers["set-cookie"]
    assert "httponly" in header.lower()
    assert "samesite=lax" in header.lower().replace(" ", "")


def test_the_csrf_cookie_is_readable_by_the_page(client, shopper):
    """It has to be: the page cannot echo a value it cannot read. Its secrecy
    from *other origins* is what makes double-submit work, not its secrecy from
    this one."""
    r = _login(client, shopper)

    assert r.cookies.get(CSRF_COOKIE)


def test_refresh_works_from_the_cookie_with_no_authorization_header(client, shopper):
    login = _login(client, shopper)
    csrf = login.cookies.get(CSRF_COOKIE)

    r = client.post("/api/en/account/session/refresh", headers={"X-CSRF-Token": csrf})

    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_refresh_without_the_csrf_header_is_refused(client, shopper):
    _login(client, shopper)

    r = client.post("/api/en/account/session/refresh")

    assert r.status_code == 403


def test_refresh_with_a_mismatched_csrf_header_is_refused(client, shopper):
    _login(client, shopper)

    r = client.post(
        "/api/en/account/session/refresh", headers={"X-CSRF-Token": "not-the-value"}
    )

    assert r.status_code == 403


def test_refresh_without_the_cookie_is_a_401(client):
    r = client.post("/api/en/account/session/refresh", headers={"X-CSRF-Token": "x"})

    assert r.status_code in (401, 403)


def test_signing_out_clears_the_refresh_cookie(client, shopper):
    login = _login(client, shopper)
    csrf = login.cookies.get(CSRF_COOKIE)

    r = client.delete("/api/en/account/session", headers={"X-CSRF-Token": csrf})

    assert r.status_code == 204, r.text
    assert not client.cookies.get(REFRESH_COOKIE)


def test_a_signed_out_session_cannot_refresh_again(client, shopper):
    """Signing out revokes the row, not just the cookie. Clearing the cookie
    alone would leave a token that still works to anyone who copied it."""
    login = _login(client, shopper)
    csrf = login.cookies.get(CSRF_COOKIE)
    stolen = login.cookies.get(REFRESH_COOKIE)
    client.delete("/api/en/account/session", headers={"X-CSRF-Token": csrf})

    # Put the cookies back by hand, standing in for someone who copied them
    # before sign-out. Set on the client rather than passed per-request: httpx
    # deprecated per-request cookies precisely because whether they persist is
    # ambiguous, and the whole point here is which value the server receives.
    client.cookies.set(REFRESH_COOKIE, stolen)
    client.cookies.set(CSRF_COOKIE, csrf)

    r = client.post(
        "/api/en/account/session/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert r.status_code in (401, 403)


def test_the_rotated_cookie_replaces_the_one_that_was_used(client, shopper):
    """Rotation revokes on use, so the browser must be given the new value or
    the next refresh presents a token that was just consumed."""
    login = _login(client, shopper)
    csrf = login.cookies.get(CSRF_COOKIE)
    first = login.cookies.get(REFRESH_COOKIE)

    rotated = client.post(
        "/api/en/account/session/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert rotated.cookies.get(REFRESH_COOKIE)
    assert rotated.cookies.get(REFRESH_COOKIE) != first
