"""Assembly — what the dependency graph and the merged route table look like."""

from __future__ import annotations

import asyncio

from app.api import LibraryApi
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.service import CatalogService
from app.module.db.repository.book_repository import BookRepository
from app.module.loan.service import CirculationService
from app.testing import effective_config
from canary_framework import Canary, LifecycleState
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


def test_every_module_mounts_under_the_api_prefix(client):
    """``@web_cocoa`` prefixes nest along dependency edges: /api + /catalog + …"""
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == EXPECTED_PATHS


def test_openapi_metadata_comes_from_the_outermost_unit(client):
    info = client.get("/openapi.json").json()["info"]
    assert info == {"title": "智能图书馆管理系统 API", "version": "1.0.0"}


def test_dependencies_start_before_their_dependents(app):
    """Topological order — settings first, the engine, then everything above it.

    ``AppConfig`` 又回到了图上：类级注解注入被删之后，配置就是一个普通 ``@cocoa``
    节点，靠 ``deps=[AppConfig]`` 声明，因此也参与拓扑排序——而且必然排在最前，
    因为谁都依赖它、它谁也不依赖。
    """
    asyncio.run(app.init())
    order = list(app.order)
    assert order[0] is AppConfig
    assert order.index(AppConfig) < order.index(Database)
    assert order.index(Database) < order.index(CatalogService)
    assert order.index(BookRepository) < order.index(CatalogService)
    assert order[-1] is LibraryApi


def test_shared_units_are_singletons(app):
    """A unit reached from two branches is instantiated once.

    Injection happens in ``start()``, not ``init()`` — the graph is built first,
    attributes are wired afterwards.
    """
    asyncio.run(app.init())
    asyncio.run(app.start())
    catalog = app[CatalogService]
    circulation = app[CirculationService]
    assert catalog.book_repository is circulation.book_repository
    assert app[Database] is catalog.database
    asyncio.run(app.stop())


def test_lifecycle_reaches_started_and_stopped(app):
    assert app.state is LifecycleState.NEW
    asyncio.run(app.init())
    assert app.state is LifecycleState.INITIALIZED
    asyncio.run(app.start())
    assert app.state is LifecycleState.STARTED
    asyncio.run(app.stop())
    assert app.state is LifecycleState.STOPPED


def test_on_start_hooks_wired_the_infrastructure(client):
    """``@on_start`` runs after injection, so the engine is built from config."""
    canary = client.canary
    assert canary[Database].engine is not None
    assert canary[EmbeddingModel].dim == effective_config(canary).embedding_dim
    assert canary[ChatModel] is not None


def test_one_config_instance_is_shared_by_the_whole_graph(client):
    """``config: AppConfig`` on four different units resolves to one object."""
    canary = client.canary
    shared = effective_config(canary)
    assert canary[EmbeddingModel].app_config is shared
    assert canary[ChatModel].app_config is shared
    assert canary[LibraryApi].app_config is shared
    # 没声明的单元不会被塞进去
    assert not hasattr(canary[CatalogService], "app_config")


def test_the_runtime_injects_nothing_it_was_not_asked_for(client):
    """注入的来源只有一个：``deps=[...]``。

    0.9.3 还会按类级注解塞进 ``log: logging.Logger`` 与配置实例；HEAD 把那条路
    删干净了，单元身上因此只会出现自己声明过的协作者。日志退回标准库的
    ``logging.getLogger(__name__)``——框架不再多认识一种声明方式。
    """
    api = client.canary[LibraryApi]
    assert not hasattr(api, "log")
    assert api.app_config is client.canary[AppConfig]


def test_health_reports_the_selected_implementations(client):
    body = client.get("/api/health").json()["data"]
    assert body == {
        "status": "ok",
        "storage": "sqlite",
        "dialect": "sqlite",
        "embedding_model": "EmbeddingModel",
        "chat_model": "ChatModel",
    }
