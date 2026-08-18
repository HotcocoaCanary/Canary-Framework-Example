"""Shared fixtures that assemble and start the real ``AppModule``.

Tests are deliberately run without a database, so service-level exceptions are
caught by the application services and surfaced as ``R.fail`` payloads.
"""

import asyncio

import pytest
from starlette.testclient import TestClient

from main import AppModule


@pytest.fixture(scope="session")
def app():
    instance = AppModule()
    asyncio.run(instance.init())
    asyncio.run(instance.start())
    return instance


@pytest.fixture(scope="session")
def client():
    with TestClient(AppModule()) as test_client:
        yield test_client
