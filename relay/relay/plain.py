"""Writing an HTTP response by hand, with no framework at all.

手写 HTTP 响应。``/metrics`` 与 ``/ready`` 不值得为它们引入一个 web 框架：ASGI 应用就是
一个三参数的协程函数，自己送两条消息就是一个响应。``asgi.App`` 只要求 ``self.app`` 是这样
一个可调用对象——是 FastAPI 应用、是别的框架的应用、还是这样一个函数，框架不关心。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

type Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
type Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
type Scope = MutableMapping[str, Any]


async def respond(send: Send, status: int, body: str, content_type: str = "text/plain") -> None:
    """Send one complete HTTP response.

    送一个完整的 HTTP 响应。
    """
    raw = body.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", f"{content_type}; charset=utf-8".encode()),
                (b"content-length", str(len(raw)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def reject(send: Send, scope: Scope, status: int = 404, body: str = "not found") -> None:
    """Refuse a request, whatever protocol it arrived on.

    拒绝一个请求，HTTP 与 WebSocket 都要管——``asgi.dispatch`` 把两种 scope 都转发进来，
    应用自己只认一种的话，另一种就会把连接挂住。
    """
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    await respond(send, status, body)


def guard(app: object, token: str, prefix: str) -> object:
    """Wrap an ASGI application so that *prefix* needs the admin token.

    一个最普通的 ASGI 中间件：两层 HTTP **共用**它。

    中间件不必是某个 Web 框架的东西——``asgi.App`` 的 ``self.app`` 就是一个 ASGI 应用，
    在 ``@init`` 里包一层即可，两个包的文档都这么说。于是口令校验这件事只写一次，两层的
    行为也就必然一致（FastAPI 的 ``BaseHTTPMiddleware`` 与 ``asgi.web`` 没有的那套东西
    都不需要）。
    """

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(prefix):
            headers = {name.lower(): value for name, value in scope["headers"]}
            if headers.get(b"x-admin-token", b"").decode("latin-1") != token:
                await respond(send, 403, '{"detail":"forbidden"}', content_type="application/json")
                return
        await app(scope, receive, send)  # type: ignore[operator]

    return guarded
