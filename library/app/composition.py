"""The composition root — one unit that makes the whole graph reachable.

它依赖每个模块的 service，于是从这里出发能走到图上的每个单元。启动它，整张图按依赖
顺序就位；退出时逆序回收。

0.10.0 之后这里没有"容器"了：``Canary(LibraryApi)`` 那一层消失，根单元自己就是入口。
谁来启动它见 ``app/wiring.py``——FastAPI 的 lifespan。

注意这个类**不认识 HTTP**。路由、状态码、OpenAPI 全在 ``app/api.py`` 那一侧；
框架 0.10.0 删掉了 ``canary_framework.web``，定位收回到依赖注入与生命周期本身，
所以两边的边界现在是一条明线，而不是一个由框架同时承担两职的类。
"""

from __future__ import annotations

from canary_framework import Canary, dep

from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.service import CatalogService
from app.module.chat.service import AssistantService
from app.module.loan.service import CirculationService
from app.module.rag.service import RagService
from app.module.reader.service import ReaderService
from config import AppConfig


class LibraryApi(Canary):
    """Everything the HTTP layer can reach, and nothing about HTTP itself."""

    config = dep(AppConfig)
    database = dep(Database)
    embeddings = dep(EmbeddingModel)
    chat_model = dep(ChatModel)

    catalog = dep(CatalogService)
    readers = dep(ReaderService)
    circulation = dep(CirculationService)
    rag = dep(RagService)
    assistant = dep(AssistantService)

    def health(self) -> dict[str, str]:
        """What a health endpoint reports —— 图里**实际**装的是哪个实现。"""
        return {
            "status": "ok",
            "storage": self.config.storage,
            "dialect": self.database.dialect,
            "embedding_model": type(self.embeddings).__name__,
            "chat_model": type(self.chat_model).__name__,
        }
