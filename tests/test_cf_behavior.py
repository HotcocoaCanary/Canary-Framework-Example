"""Framework-level behavior checks against Canary 0.9's web extension.

These tests use a small, standalone ``@web_cocoa`` unit so they do not depend on
the application's database services.
"""

import asyncio

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from canary_framework import Canary
from canary_framework.web import get, post, web_cocoa
from canary_framework.web.error.web import RouteRegistrationError


class Item(BaseModel):
    a: int


@web_cocoa(title="Toy API", version="0.1.0")
class Toy:
    @get("/toy/req")
    async def required_query(self, q: str):
        return {"q": q}

    @get("/toy/flag")
    async def bool_query(self, on: bool = False):
        return {"on": on}

    @post("/toy/items")
    async def create_model(self, item: Item) -> dict:
        return {"a": item.a}

    @get("/toy/silent")
    async def silent(self, page: int = 1, keyword: str | None = None):
        return {"page": page, "keyword": keyword}


@pytest.fixture(scope="module")
def toy_client():
    with TestClient(Canary(Toy)) as test_client:
        yield test_client


def test_missing_required_query_is_422(toy_client):
    resp = toy_client.get("/toy/req")
    assert resp.status_code == 422


def test_present_required_query_binds(toy_client):
    resp = toy_client.get("/toy/req", params={"q": "hi"})
    assert resp.status_code == 200
    assert resp.json() == {"q": "hi"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
    ],
)
def test_bool_query_parsing(toy_client, raw, expected):
    resp = toy_client.get("/toy/flag", params={"on": raw})
    assert resp.status_code == 200
    assert resp.json() == {"on": expected}


def test_bool_query_invalid_is_422(toy_client):
    resp = toy_client.get("/toy/flag", params={"on": "maybe"})
    assert resp.status_code == 422


def test_body_model_binding(toy_client):
    resp = toy_client.post("/toy/items", json={"a": 1})
    assert resp.status_code == 200
    assert resp.json() == {"a": 1}


def test_query_param_defaults_and_binding(toy_client):
    resp = toy_client.get("/toy/silent", params={"page": 3, "keyword": "hello"})
    assert resp.status_code == 200
    assert resp.json() == {"page": 3, "keyword": "hello"}

    default_resp = toy_client.get("/toy/silent")
    assert default_resp.status_code == 200
    assert default_resp.json() == {"page": 1, "keyword": None}


def test_route_collision_raises_registration_error():
    @web_cocoa
    class Collide:
        @get("/ping")
        async def ping(self):
            return "a"

        @get("/ping")
        async def other(self):
            return "b"

    app = Canary(Collide)
    asyncio.run(app.init())
    with pytest.raises(RouteRegistrationError, match="duplicate route"):
        asyncio.run(app.start())
