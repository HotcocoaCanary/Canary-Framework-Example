"""Assembly — the dependency graph, the route table, and the seam between them."""

from __future__ import annotations

import asyncio

from canary_framework import deps_of, init, scope_of

from app.composition import LibraryApi
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.service import CatalogService
from app.module.db.repository.book_repository import BookRepository
from app.module.loan.service import CirculationService
from app.testing import unit
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


# --- 路由表：FastAPI 那一侧 ------------------------------------------------


def test_every_module_mounts_under_its_own_absolute_prefix(client):
    """前缀是绝对的：每个 router 自己写全 ``/api/<模块>``，不再沿依赖边下沉。"""
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == EXPECTED_PATHS


def test_openapi_metadata_comes_from_the_fastapi_app(client):
    info = client.get("/openapi.json").json()["info"]
    assert info["title"] == "智能图书馆管理系统 API"
    assert info["version"] == "1.0.0"


def test_the_interactive_docs_render(client):
    """0.9.x 里 OpenAPI schema 生成会打挂 ``/docs``；换成 FastAPI 之后这是它的本职。"""
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# --- 依赖图：Canary 那一侧 -------------------------------------------------


def test_the_root_reaches_every_service():
    """根单元依赖每个模块的 service，于是整张图从它可达。"""
    from app.module.chat.service import AssistantService
    from app.module.rag.service import RagService
    from app.module.reader.service import ReaderService

    assert set(deps_of(LibraryApi)) == {
        AppConfig,
        Database,
        EmbeddingModel,
        ChatModel,
        CatalogService,
        ReaderService,
        CirculationService,
        RagService,
        AssistantService,
    }


def test_dependencies_start_before_their_dependents():
    """推进沿依赖向下：一个单元进入某阶段之前，它的依赖已经完成该阶段。"""
    order: list[type] = []

    async def run() -> None:
        root = LibraryApi()
        await root.init()
        # 台账记录的就是进入顺序
        order.extend(type(u) for u in scope_of(root).entered(init).values())

    asyncio.run(run())
    assert order.index(AppConfig) < order.index(Database)
    assert order.index(Database) < order.index(CatalogService)
    assert order.index(BookRepository) < order.index(CatalogService)
    assert order[-1] is LibraryApi, "根单元最后进入——它依赖所有人"


def test_shared_units_are_singletons(root):
    """A unit reached from two branches is instantiated once."""
    catalog = unit(root, CatalogService)
    circulation = unit(root, CirculationService)
    assert catalog.books is circulation.books
    assert unit(root, Database) is catalog.database


def test_one_config_instance_is_shared_by_the_whole_graph(root):
    """``config = dep(AppConfig)`` 写在四个不同单元上，解析到同一个对象。"""
    shared = unit(root, AppConfig)
    assert unit(root, EmbeddingModel).config is shared
    assert unit(root, ChatModel).config is shared
    assert root.config is shared


def test_start_hooks_wired_the_infrastructure(root):
    """``@start`` 在依赖的 ``@start`` 之后运行，所以引擎是用最终配置建的。"""
    assert unit(root, Database).engine is not None
    assert unit(root, EmbeddingModel).dim == unit(root, AppConfig).embedding_dim


def test_a_unit_only_carries_what_it_declared(root):
    """注入的来源只有一个：``dep(...)``。框架不会多塞日志、配置或任何别的东西。"""
    catalog = unit(root, CatalogService)
    assert not hasattr(catalog, "log")
    assert not hasattr(catalog, "config"), "CatalogService 没声明 AppConfig"
    assert hasattr(catalog, "database")


def test_the_attribute_name_is_the_applications_choice(root):
    """``books = dep(BookRepository)`` —— 不再是类名的 snake_case。"""
    catalog = unit(root, CatalogService)
    assert catalog.books is unit(root, BookRepository)
    assert not hasattr(catalog, "book_repository")


# --- 两侧的接触面 -----------------------------------------------------------


def test_the_http_layer_resolves_units_out_of_the_running_scope(client, root):
    """``unit(Cls)`` 是 FastAPI 依赖，取的就是 lifespan 启动的那张图里的实例。"""
    body = client.get("/api/health").json()["data"]
    assert body == root.health()


def test_health_reports_the_implementations_actually_in_the_graph(client):
    body = client.get("/api/health").json()["data"]
    assert body == {
        "status": "ok",
        "storage": "sqlite",
        "dialect": "sqlite",
        "embedding_model": "EmbeddingModel",
        "chat_model": "ChatModel",
    }


def test_each_app_gets_its_own_graph():
    """两个各自构造的根是两张互不相干的图——作用域即是图。"""

    async def run() -> tuple[object, object]:
        a, b = LibraryApi(), LibraryApi()
        await a.init()
        await b.init()
        return scope_of(a), scope_of(b)

    scope_a, scope_b = asyncio.run(run())
    assert scope_a is not scope_b
    assert scope_a.instances[AppConfig] is not scope_b.instances[AppConfig]
