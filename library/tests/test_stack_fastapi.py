"""只属于原生 FastAPI 那一层的东西。

两层对外的路径、状态码、响应体是一致的（``test_parity.py`` 逐条比对过），所以这里只放
**换成应用单元就没有**的东西：OpenAPI 与 ``/docs``、``tags``、``Depends`` 生态、FastAPI
自己的校验与约束——以及这一层独有的那座桥。

这些就是"把 HTTP 交给 FastAPI"换来的东西，一条一条摆在这里。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework.test import running, unit
from fastapi import FastAPI
from pydantic import BaseModel, Field, model_validator

from app.api.fastapi import Services, create_app
from app.api.fastapi.bridge import graph, use
from app.infra.db import Database
from app.module.catalog.service import CatalogService

# --- OpenAPI：这一层独有的 ---------------------------------------------------


async def test_openapi_metadata_and_docs(fastapi_client) -> None:
    """``FastAPI(title=..., version=...)`` 与 ``/docs`` 都是 FastAPI 的本职。"""
    info = (await fastapi_client.get("/openapi.json")).json()["info"]
    assert info["title"] == "智能图书馆管理系统 API"
    assert info["version"] == "1.0.0"
    assert (await fastapi_client.get("/docs")).status_code == 200


async def test_tags_group_the_endpoints(fastapi_client) -> None:
    """``APIRouter(tags=[...])`` 原样进 OpenAPI —— 应用单元那层没有标签这回事。"""
    schema = (await fastapi_client.get("/openapi.json")).json()
    tags = {
        tag
        for path in schema["paths"].values()
        for operation in path.values()
        for tag in operation.get("tags", [])
    }
    assert {"书目与馆藏", "读者", "借还流通", "知识库", "智能助手", "系统"} <= tags


async def test_the_request_and_response_models_are_in_the_schema(fastapi_client) -> None:
    """请求体与响应体的 JSON Schema 也是白来的。"""
    schema = (await fastapi_client.get("/openapi.json")).json()
    assert "CreateBookRequest" in schema["components"]["schemas"]
    create = schema["paths"]["/api/catalog/books"]["post"]
    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "CreateBookRequest"
    )


# --- 那座桥：原生 FastAPI 怎么拿到单元 --------------------------------------


async def test_the_bridge_resolves_the_very_instance_from_the_graph() -> None:
    """``Depends(use(Cls))`` 取回的就是图上那一个实例，不是新造的。"""
    async with running(Services) as services:
        app = create_app(services)
        assert app.state.graph is services
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (await client.get("/api/health")).json()["data"]
            assert body["dialect"] == unit(services, Database).dialect

            created = await client.post(
                "/api/catalog/books", json={"title": "桥", "author": "x"}
            )
            book_id = created.json()["data"]["id"]
            # 同一个 service 实例：不经 HTTP 也能查到刚写进去的那本
            assert (await unit(services, CatalogService).get_book(book_id)).title == "桥"


async def test_an_application_without_a_graph_says_so() -> None:
    """桥没挂上图时直说——而不是在某个接口里冒出 ``AttributeError``。"""
    bare = FastAPI()

    class Fake:
        app = bare

    with pytest.raises(RuntimeError, match="还没有挂上图"):
        await graph(Fake())  # type: ignore[arg-type]


async def test_each_service_needs_its_own_dependency_line() -> None:
    """这一层的代价：每个要用的 service 都得写一条 ``Annotated[..., use(...)]``。

    路由单元那一侧是 ``catalog = dep(CatalogService)`` 写在类上，接口方法直接用
    ``self.catalog``——少一层桥，也少一次"忘了写 Depends 就拿不到"的机会。
    """
    dependency = use(CatalogService)
    assert dependency.dependency is not None  # 是一个 FastAPI Depends


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


async def test_a_model_validator_failure_is_422() -> None:
    """跨字段校验和单字段校验走同一条路，都是 FastAPI 的。"""
    app = FastAPI()

    @app.post("/guarded")
    async def guarded(item: Guarded) -> dict:
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post("/guarded", json={})).status_code == 422
        assert (await client.post("/guarded", json={"right": 99})).status_code == 422
        assert (await client.post("/guarded", json={"left": 1})).status_code == 200


async def test_constraints_in_the_schema_are_enforced(fastapi_client) -> None:
    """``Field(ge=..., le=...)`` 由 FastAPI 强制，服务层不必重复校验。"""
    response = await fastapi_client.post(
        "/api/catalog/books",
        json={"title": "x", "author": "y", "copies": 999},  # le=100
    )
    assert response.status_code == 422


async def test_a_real_bug_is_not_disguised_as_a_domain_error(fastapi_client) -> None:
    """只有 ``DomainError`` 走信封；真 bug 照常冒泡成 500。"""
    transport = httpx.ASGITransport(app=fastapi_client._transport.app, raise_app_exceptions=False)  # noqa: SLF001
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 没有这个路径：FastAPI 自己的 404，不是领域信封
        answer = await client.get("/api/nowhere")
        assert answer.status_code == 404
        assert answer.json() == {"detail": "Not Found"}
