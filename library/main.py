"""智能图书馆管理系统 — Canary Framework entry point.

``Canary`` 本身就是 ASGI 应用：lifespan 协议驱动 ``init`` / ``start`` / ``stop``，
从根可达的每个 ``@web_cocoa`` 单元把路由并进同一个 app（外加 ``/docs`` 与
``/openapi.json``）。

组装到此为止：``Canary(LibraryApi)``，没有第二个参数。最终版删掉了 ``provide=``，
图上的实例全部由框架无参构造，所以"用哪个模型实现"不再是组装期的选择，而是
``EmbeddingModel`` / ``ChatModel`` 自己读 ``AppConfig`` 挑后端（见 ``app/infra/ai.py``）。
"""

import uvicorn
from canary_framework import Canary

from app.api import LibraryApi


app = Canary(LibraryApi)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010, lifespan="on")
