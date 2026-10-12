"""智能图书馆管理系统 — 入口（我们的服务器单元监听）。

同一份业务，两层 HTTP，用 ``--stack`` 挑一层::

    python main.py                          # canary 版（路由与应用都是单元），:8010
    python main.py --stack fastapi          # 原生 FastAPI 版，:8110
    python main.py --stack canary --port 9000

``Gateway`` 是监听的单元：它在 ``@start`` 里绑定端口并服务一个 ASGI 应用，在 ``@stop`` 里
先停止监听，再由框架逆序回收数据库等依赖。进程的生命周期归 Canary——所以信号由这里自己接。

两层的区别只在"服务什么"：canary 版服务的是一个应用单元，fastapi 版在 ``@init`` 里把一个
FastAPI 对象赋给 ``self.app``。服务器只认 ASGI 协议，不问出处。

想让 uvicorn 直接跑应用单元（不要我们的服务器单元），见 ``asgi.py``。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from app.api import NAMES, gateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="图书馆 API（两层 HTTP 任选一层）")
    parser.add_argument("--stack", choices=NAMES, default="canary", help="HTTP 层（默认 canary）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取该层的 port）")
    parser.add_argument("--host", default=None, help="监听地址")
    return parser.parse_args()


async def serve(stack: str, host: str | None, port: int | None) -> None:
    log = logging.getLogger("library")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    server = gateway(stack)()
    if host is not None:
        server.host = host
    if port is not None:
        server.port = port

    async with server:
        log.info("[%s] http://%s:%s", stack, server.host, server.port)
        await stop.wait()
        log.info("[%s] 收到停止信号，回收整张图", stack)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    args = parse_args()
    asyncio.run(serve(args.stack, args.host, args.port))


if __name__ == "__main__":
    main()
