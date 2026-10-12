"""青瓷商城后台 — 入口。

这个场景的入口和另外两个**故意不一样**：进程的主人是 uvicorn。

    uv run python main.py
    uv run uvicorn shop.asgi:app --reload --port 8040

生命周期由 ASGI 的 lifespan 驱动，图在 ``shop/asgi.py`` 的 ``lifespan`` 里启动与回收。
好处是老的部署方式、``--reload``、``--workers`` 全都不动；代价是一个进程只有一个应用、
一个端口，而"全图起来之后"这个位置只能借 lifespan 来表达。
"""

from __future__ import annotations

import logging

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    uvicorn.run("shop.asgi:app", host="0.0.0.0", port=8040, lifespan="on")


if __name__ == "__main__":
    main()
