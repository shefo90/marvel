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
