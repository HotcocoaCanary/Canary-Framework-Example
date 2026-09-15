"""智能图书馆管理系统 — 入口。

``app/api.py`` 组装 FastAPI 应用，它的 lifespan 负责启动与回收 Canary 那张图。
uvicorn 只管跑 ASGI，对 Canary 一无所知。
"""

import uvicorn

from app.api import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
