"""框架级行为验证：与本项目解耦的玩具 service。

已实测确认：@service() 注册表以 module 树为作用域，
本文件定义的玩具类不会污染 conftest 中的 AppModule 装配。
"""

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from canary_framework import module, service
from canary_framework.core.module import ModuleBase
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase


class Item(BaseModel):
    a: int


@service()
class Toy(ServiceBase):
    router = Router(prefix="/toy")

    @router.get("/req?q={q}")
    async def required_query(self, q: str):
        return {"q": q}

    @router.get("/flag?on={on}")
    async def bool_query(self, on: bool = False):
        return {"on": on}

    @router.post("/items")
    async def create_model(self, item: Item):
        return {"a": item.a}, 201

    @router.post("/dicts")
    async def create_dict(self, item: dict):
        return item, 201

    @router.get("/silent?page={page}")
    async def silent(self, page: int = 1, keyword: str | None = None):
        # keyword 未在路径字符串声明 —— 按文档语义永远保持默认值
        return {"page": page, "keyword": keyword}


@pytest.fixture(scope="module")
def toy_client():
    app = Toy()
    app.init()
    return TestClient(app.asgi_app, raise_server_exceptions=False)


def test_missing_required_query_is_422(toy_client):
    """矩阵 #5：缺失必填 query → 422（0.5.2 之前是 500）。"""
    assert toy_client.get("/toy/req").status_code == 422


def test_present_required_query_binds(toy_client):
    resp = toy_client.get("/toy/req?q=hi")
    assert resp.status_code == 200
    assert resp.json() == {"q": "hi"}


@pytest.mark.parametrize(
    "raw,expected",
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("false", False), ("No", False), ("off", False)],
)
def test_bool_query_parsing(toy_client, raw, expected):
    """矩阵 #6：bool query 大小写无关解析。"""
    resp = toy_client.get(f"/toy/flag?on={raw}")
    assert resp.status_code == 200
    assert resp.json() == {"on": expected}


def test_bool_query_invalid_is_422(toy_client):
    """矩阵 #6：无法识别的 bool 值 → 422（0.5.2 之前只认字面量 true）。"""
    assert toy_client.get("/toy/flag?on=maybe").status_code == 422


def test_tuple_return_sets_status_code(toy_client):
    """矩阵 #7：(body, status_code) 元组正确设置状态码（0.5.2 之前恒 200）。"""
    resp = toy_client.post("/toy/items", json={"a": 1})
    assert resp.status_code == 201
    assert resp.json() == {"a": 1}


@pytest.mark.xfail(
    strict=True,
    reason="doc/bug/002：dict 请求体参数（无显式 request_model）未绑定 → TypeError 500",
)
def test_dict_body_param_binds(toy_client):
    """web.md 的示例写法 `item: dict` —— 按文档应正常绑定。"""
    resp = toy_client.post("/toy/dicts", json={"a": 1})
    assert resp.status_code == 201


def test_undeclared_query_param_keeps_default(toy_client):
    """文档语义确认：带默认值但未在路径字符串声明的参数永不从查询串绑定。

    （对应应用层遗留问题：kb/router.py list_public 的 keyword 参数。）
    """
    resp = toy_client.get("/toy/silent?page=3&keyword=hello")
    assert resp.status_code == 200
    assert resp.json() == {"page": 3, "keyword": None}


def test_route_collision_raises_value_error():
    """矩阵 #2：相同 (method, full_path) 在组装时抛 ValueError。"""

    @service()
    class CollideA(ServiceBase):
        router = Router()

        @router.get("/ping")
        async def ping(self):
            return "a"

    @service()
    class CollideB(ServiceBase):
        router = Router()

        @router.get("/ping")
        async def ping(self):
            return "b"

    @module(services=[CollideA, CollideB])
    class CollideApp(ModuleBase):
        pass

    app = CollideApp()
    app.init()
    with pytest.raises(ValueError, match="Route collision: GET /ping"):
        _ = app.asgi_app
