"""Fixtures — a fully assembled application per test, on its own in-memory DB.

``AppConfig`` defaults to ``storage=sqlite`` with ``sqlite_path=":memory:"``, and
``Database`` pins an in-memory SQLite to a single connection, so each ``Canary``
instance gets a private schema that disappears with it.  No external service is
needed: the embedding and chat models default to their deterministic local
implementations.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.api import LibraryApi
from app.infra.db import Database
from canary_framework import Canary


@pytest.fixture
def app() -> Canary:
    """An un-started runtime — for tests that drive the lifecycle themselves."""
    return Canary(LibraryApi)


@pytest.fixture
def client(app: Canary):
    """A started application; ``TestClient``'s context manager drives lifespan."""
    with TestClient(app) as test_client:
        test_client.canary = app
        yield test_client


@pytest.fixture
def database(client) -> Database:
    """The live ``Database`` unit, for tests that need to age rows directly."""
    return client.canary[Database]
