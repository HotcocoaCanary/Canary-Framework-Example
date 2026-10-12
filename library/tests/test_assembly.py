"""Assembly — the dependency graph, and the route table that is part of it.

这个文件对**两层 HTTP 各跑一遍**：依赖图的形状、路径表、单例语义都不该因为换了一层 HTTP
而不同。两层的类是不同的类，所以类从 ``layer`` fixture 取（见 ``conftest.py``）。

只属于 FastAPI 那一层的东西（OpenAPI 的 ``info``、``/docs``）在 ``test_stack_fastapi.py``。
"""

from __future__ import annotations

import asyncio

from canary_framework import init, scope_of
from canary_framework.test import unit

from app.api import root_unit
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.service import CatalogService
from app.module.db.repository.book_repository import BookRepository
from app.module.loan.service import CirculationService
from app.testing import paths_of
from config import AppConfig

EXPECTED_PATHS = {
    "/api/health",
    "/api/catalog/books",
    "/api/catalog/books/{book_id}",
    "/api/catalog/books/{book_id}/copies",
    "/api/catalog/copies/{copy_id}",
    "/api/catalog/categories",
    "/api/readers/",
    "/api/readers/{reader_id}",
    "/api/readers/{reader_id}/fines/payment",
    "/api/circulation/borrow",
    "/api/circulation/return",
    "/api/circulation/loans/{loan_id}",
    "/api/circulation/loans/{loan_id}/renew",
    "/api/circulation/readers/{reader_id}/loans",
    "/api/circulation/readers/{reader_id}/reservations",
    "/api/circulation/overdue",
    "/api/circulation/reservations",
    "/api/circulation/reservations/{reservation_id}",
    "/api/rag/documents",
    "/api/rag/documents/{doc_id}",
    "/api/rag/documents/{doc_id}/reindex",
    "/api/rag/books/{book_id}/index",
    "/api/rag/search",
    "/api/assistant/ask",
    "/api/assistant/sessions",
    "/api/assistant/sessions/{session_id}/ask",
    "/api/assistant/sessions/{session_id}/messages",
    "/api/assistant/sessions/{session_id}",
}


# --- 路由表：依赖图的一部分 -------------------------------------------------


async def test_prefixes_add_up_along_the_dependency_edges(stack, root, app):
    """两层 HTTP 注册出**同一张路径表**——"换一层 HTTP 不影响对外形状"的那条断言。

    canary 层的前缀逐层叠加（``Api`` 写 ``/api``，模块只写自己那一段）；fastapi 层是
    ``APIRouter(prefix=...)`` 一层层 include。两种写法，同一张表。
    """
    assert paths_of(stack, root, app) == EXPECTED_PATHS


# --- 依赖图：Canary 那一侧 -------------------------------------------------


def test_dependencies_start_before_their_dependents(stack):
    """推进沿依赖向下：一个单元进入某阶段之前，它的依赖已经完成该阶段。"""
    order: list[type] = []

    async def run() -> None:
        root = root_unit(stack)()
        await root.init()
        # 台账记录的就是进入顺序
        order.extend(type(u) for u in scope_of(root).entered(init).values())

    asyncio.run(run())
    assert order.index(AppConfig) < order.index(Database)
    assert order.index(Database) < order.index(CatalogService)
    assert order.index(BookRepository) < order.index(CatalogService)
    assert order[-1] is root_unit(stack), "根单元最后进入——它依赖所有人"


async def test_shared_units_are_singletons(root):
    """A unit reached from two branches is instantiated once."""
    catalog = unit(root, CatalogService)
    circulation = unit(root, CirculationService)
    assert catalog.books is circulation.books
    assert unit(root, Database) is catalog.database


async def test_one_config_instance_is_shared_by_the_whole_graph(root):
    """``config = dep(AppConfig)`` 写在几个不同单元上，解析到同一个对象。"""
    shared = unit(root, AppConfig)
    assert unit(root, EmbeddingModel).config is shared
    assert unit(root, ChatModel).config is shared
    assert unit(root, CatalogService).database.config is shared


async def test_start_hooks_wired_the_infrastructure(root):
    """``@start`` 在依赖的 ``@start`` 之后运行，所以引擎是用最终配置建的。"""
    assert unit(root, Database).engine is not None
    assert unit(root, EmbeddingModel).dim == unit(root, AppConfig).embedding_dim


async def test_a_unit_only_carries_what_it_declared(root):
    """注入的来源只有一个：``dep(...)``。框架不会多塞日志、配置或任何别的东西。"""
    catalog = unit(root, CatalogService)
    assert not hasattr(catalog, "log")
    assert not hasattr(catalog, "config"), "CatalogService 没声明 AppConfig"
    assert hasattr(catalog, "database")


async def test_the_attribute_name_is_the_applications_choice(root):
    """``books = dep(BookRepository)`` —— 不再是类名的 snake_case。"""
    catalog = unit(root, CatalogService)
    assert catalog.books is unit(root, BookRepository)
    assert not hasattr(catalog, "book_repository")


# --- 接口方法就是绑定方法 ---------------------------------------------------


async def test_an_endpoint_answers_from_the_units_in_the_graph(client, root):
    """``/api/health`` 报的就是图上**实际**装的那几个实现——两层都是。"""
    body = (await client.get("/api/health")).json()["data"]
    assert body["dialect"] == unit(root, Database).dialect
    assert body["embedding_model"] == type(unit(root, EmbeddingModel)).__name__
    assert body["storage"] == unit(root, AppConfig).storage


async def test_health_reports_the_implementations_actually_in_the_graph(client):
    body = (await client.get("/api/health")).json()["data"]
    assert body == {
        "status": "ok",
        "storage": "sqlite",
        "dialect": "sqlite",
        "embedding_model": "EmbeddingModel",
        "chat_model": "ChatModel",
    }


def test_each_app_gets_its_own_graph(stack):
    """两个各自构造的根是两张互不相干的图——作用域即是图。"""

    async def run() -> tuple[object, object]:
        a, b = root_unit(stack)(), root_unit(stack)()
        await a.init()
        await b.init()
        return scope_of(a), scope_of(b)

    scope_a, scope_b = asyncio.run(run())
    assert scope_a is not scope_b
    assert scope_a.instances[AppConfig] is not scope_b.instances[AppConfig]
