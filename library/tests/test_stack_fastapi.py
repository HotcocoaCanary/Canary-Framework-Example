"""只属于 FastAPI 那一层的东西。

两层 HTTP 对外的路径、状态码、响应体是一致的（``test_assembly.py`` 与
``test_parity.py`` 钉住了这一点），所以这里只放**换成 web 版就没有**的东西：OpenAPI 与
``/docs``、``tags``、``Depends`` 生态、FastAPI 自己的校验与约束。

这些就是选 ``asgi.fastapi`` 而不是 ``asgi.web`` 的理由，一条一条摆在这里。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework import dep
from canary_framework.asgi.fastapi import Router, get, post
from canary_framework.test import running
from pydantic import BaseModel, Field, model_validator

from app.api.fastapi import LibraryApi


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- OpenAPI：这一层独有的 ---------------------------------------------------


async def test_openapi_metadata_comes_from_the_class_parameters(fastapi_client) -> None:
    """``class LibraryApi(App, title=..., version=...)`` —— 类参数原样传给 FastAPI。"""
    info = (await fastapi_client.get("/openapi.json")).json()["info"]
    assert info["title"] == "智能图书馆管理系统 API"
    assert info["version"] == "1.0.0"


async def test_the_interactive_docs_render(fastapi_client) -> None:
    """``/docs`` 是 FastAPI 的本职。web 版没有这个，也就没有这条测试的对偶。"""
    assert (await fastapi_client.get("/docs")).status_code == 200
    assert (await fastapi_client.get("/openapi.json")).status_code == 200


async def test_tags_group_the_endpoints(fastapi_client) -> None:
    """``Router`` 的 ``tags`` 原样进 OpenAPI —— web 版的路由单元没有这个参数。"""
    schema = (await fastapi_client.get("/openapi.json")).json()
    tags = {tag for path in schema["paths"].values() for op in path.values() for tag in op.get("tags", [])}
    assert {"书目与馆藏", "读者", "借还流通", "知识库", "智能助手", "系统"} <= tags


async def test_the_request_and_response_models_are_in_the_schema(fastapi_client) -> None:
    """请求体与响应体的 JSON Schema 也是白来的。"""
    schema = (await fastapi_client.get("/openapi.json")).json()
    assert "CreateBookRequest" in schema["components"]["schemas"]
    create = schema["paths"]["/api/catalog/books"]["post"]
    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "CreateBookRequest"
    )


# --- FastAPI 的校验 ---------------------------------------------------------


class Guarded(BaseModel):
    """必须定义在模块层：``get_type_hints`` 看不见函数局部作用域。"""

    left: int | None = None
    right: int | None = Field(default=None, le=10)

    @model_validator(mode="after")
    def _one_of(self) -> Guarded:
        if self.left is None and self.right is None:
            raise ValueError("left / right 至少提供一个")
        return self


class ProbeApi(Router, prefix="/probe", tags=["探针"]):
    """A router unit used only by these tests."""

    @post("/guarded")
    async def guarded(self, item: Guarded) -> dict:
        return {"ok": True}

    @get("/bug")
    async def bug(self) -> dict:
        raise ZeroDivisionError("这是真 bug")


class Probed(LibraryApi):
    """继承应用单元：标题、路由、异常处理器都带过来，再多挂一个路由单元。"""

    probe = dep(ProbeApi)


async def test_a_model_validator_failure_is_also_422() -> None:
    """跨字段校验和单字段校验走同一条路，都是 FastAPI 的。"""
    async with running(Probed) as api, _client(api.app) as http:
        assert (await http.post("/probe/guarded", json={})).status_code == 422
        assert (await http.post("/probe/guarded", json={"right": 99})).status_code == 422
        assert (await http.post("/probe/guarded", json={"left": 1})).status_code == 200


async def test_constraints_in_the_schema_are_enforced(fastapi_client) -> None:
    """``Field(ge=..., le=...)`` 由 FastAPI 强制，服务层不必重复校验。"""
    response = await fastapi_client.post(
        "/api/catalog/books",
        json={"title": "x", "author": "y", "copies": 999},  # le=100
    )
    assert response.status_code == 422


async def test_a_real_bug_is_not_disguised_as_a_domain_error() -> None:
    """只有 ``DomainError`` 走信封；真 bug 照常冒泡成 500。"""
    async with running(Probed) as api, _client(api.app) as http:
        assert (await http.get("/probe/bug")).status_code == 500


async def test_a_subclass_of_the_app_keeps_its_routes_and_adds_its_own() -> None:
    async with running(Probed) as api, _client(api.app) as http:
        paths = set((await http.get("/openapi.json")).json()["paths"])
        assert {"/api/health", "/probe/bug"} <= paths


# --- 新的路由标记：FastAPI 的装饰器，录下来 ---------------------------------


async def test_a_path_is_required_just_like_in_fastapi() -> None:
    """标记就是 FastAPI 的同名装饰器，所以路径必须写——省略路径会当场报错。

    "前缀本身"在路由单元里写 ``@get("")``（本项目 ``/api/readers/`` 那几条写的是
    ``@post("/")``，所以带尾斜杠）。
    """
    with pytest.raises(TypeError, match="takes a path"):

        class Pathless(Router, prefix="/x"):
            @get
            async def listing(self) -> dict:
                return {}


async def test_the_marks_keep_fastapis_own_signature() -> None:
    """``@post(status_code=201, summary=...)`` 这类参数原样传给 ``APIRouter.post``。"""
    import inspect

    assert "status_code" in inspect.signature(post).parameters
    assert "response_model" in inspect.signature(get).parameters
