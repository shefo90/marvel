"""Shared test fixtures.

Tests run against the live development database. Every test that writes does so
inside a transaction that is rolled back, so the suite leaves no residue and can
be run repeatedly without reseeding.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import Engine, SessionLocal  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    """A session whose work is always rolled back."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def conn():
    """A raw connection in an explicit transaction, rolled back after the test.

    Used for the trigger tests, which need to observe database-side behaviour
    (audit rows written by AFTER UPDATE triggers) rather than ORM behaviour.
    """
    connection = Engine.connect()
    trans = connection.begin()
    try:
        yield connection
    finally:
        trans.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _purge_orders_this_test_placed():
    """Delete orders committed during the test, so the suite leaves no residue.

    Most tests here write inside a transaction the ``db`` fixture rolls back.
    The checkout tests cannot: they place orders over HTTP, and the request
    handler commits its own session. Nothing undid those, so every full run left
    another dozen orders behind -- the development database had accumulated
    1,115 of them by the time anyone counted.

    Identifying them by ``id > max(id) at test start`` rather than by a naming
    convention means a test does not have to opt in or remember to clean up,
    which is the property the previous arrangement lacked. ``orders.id`` is a
    BIGSERIAL, so the watermark is monotonic even across rolled-back inserts
    that burned sequence values.

    Failures are swallowed. This is cleanup: a purge that cannot run must not
    turn a passing test red, and the worst case is the residue the suite had
    before.
    """
    from sqlalchemy import func, select

    from models.orders import Order
    from repositories.maintenance import delete_orders

    probe = SessionLocal()
    try:
        watermark = probe.execute(select(func.max(Order.id))).scalar() or 0
    finally:
        probe.close()

    yield

    session = SessionLocal()
    try:
        leaked = session.execute(
            select(Order.id).where(Order.id > watermark)
        ).scalars().all()
        if leaked:
            delete_orders(session, leaked)
            session.commit()
    except Exception:  # noqa: BLE001 - see docstring
        session.rollback()
    finally:
        session.close()
