"""智能图书馆管理系统 — 入口。

同一份业务，两层 HTTP，用 ``--stack`` 挑一层::

    python main.py                          # fastapi 版，:8010
    python main.py --stack web              # web 版，:8011
    python main.py --stack web --port 9000  # 自己指定端口

``Gateway`` 是监听的单元：它依赖某一层的 ``LibraryApi``，于是在 ``@start`` 里绑定端口并
服务它，在 ``@stop`` 里先停止监听，再由框架逆序回收数据库等依赖。进程的生命周期归
Canary，uvicorn 只是被 ``Gateway`` 驱动的服务器——所以没有 ``uvicorn main:app``，信号也
由这里自己接。

``--stack`` 不能做成运行期的参数塞给同一个 ``Gateway``：``dep()`` 是写在类上的声明，图是
静态的。所以两个栈各有一个 ``Gateway``（见 ``app/api/``），这里只是按名字取一个。
``--port`` 不同——它是普通类属性，赋值即可，只要在 ``@start`` 之前。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from app.api import NAMES, gateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="图书馆 API（两层 HTTP 任选一层）")
    parser.add_argument("--stack", choices=NAMES, default="fastapi", help="HTTP 层（默认 fastapi）")
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
