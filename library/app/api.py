"""The composition root — one web unit that owns assembly, and nothing else.

它依赖每个模块的 router，于是整张图从这里可达；``@web_cocoa`` 的 ``title`` /
``version`` 也取自最外层的 web 单元，也就是它。

两处随框架收窄而改变的写法：

**前缀是绝对的。** 0.9.2 的嵌套前缀（``/api`` 沿依赖边下沉到 ``CatalogRouter``）
被删了——依赖关系说的是启动顺序和谁能调谁，URL 说的是对外的资源命名，框架不再让
前者决定后者。所以每个 router 自己写全 ``prefix="/api/catalog"``。多打几个字，
换来的是"这条路由挂在哪儿"只看一处就知道，不必再顺着 deps 往上爬。

**异常映射没有了。** ``@on_request_error`` 被删，框架只剩三条固定出路：
绑定失败 → 422、``HTTPError`` → 自带状态码、其余 → JSON 500。领域异常要变成
``{code, data, msg}`` 信封，只能由应用自己接——接的地方是 ``app.common.errors.ok()``，
每个 handler 本来就要过它。见那个模块的说明。
"""

from __future__ import annotations

from app.common.response import R
from app.infra.ai import ChatModel, EmbeddingModel
from app.infra.db import Database
from app.module.catalog.router import CatalogRouter
from app.module.chat.router import AssistantRouter
from app.module.loan.router import CirculationRouter
from app.module.rag.router import RagRouter
from app.module.reader.router import ReaderRouter
from canary_framework.web import get, web_cocoa
from config import AppConfig


@web_cocoa(
    prefix="/api",
    deps=[
        AppConfig,
        Database,
        EmbeddingModel,
        ChatModel,
        CatalogRouter,
        ReaderRouter,
        CirculationRouter,
        RagRouter,
        AssistantRouter,
    ],
    title="智能图书馆管理系统 API",
    version="1.0.0",
    tags=["系统"],
)
class LibraryApi:
    app_config: AppConfig
    database: Database
    embedding_model: EmbeddingModel
    chat_model: ChatModel

    @get("/health")
    async def health(self) -> R[dict]:
        return R.ok(
            {
                "status": "ok",
                "storage": self.app_config.storage,
                "dialect": self.database.dialect,
                # 报告图里**实际**装的是哪个实现，而不是配置说应该是哪个。
                "embedding_model": type(self.embedding_model).__name__,
                "chat_model": type(self.chat_model).__name__,
            }
        )
