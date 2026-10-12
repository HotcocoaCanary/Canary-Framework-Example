"""``/ws/events`` —— the WebSocket side, also just an application unit.

WebSocket 也是一个应用单元：**普通的 ``Canary`` 加一个 ``async def __call__``**，不继承
任何东西。ASGI 的 WebSocket 协议写起来不比 HTTP 复杂，而且这样一来"实时流"和"REST 接口"
在图上是**并列的两个应用**，只是 ``path`` 不同，由同一个 ``Server`` 在同一个端口上服务。

它不属于任何 web 框架（我们的应用单元也不做 WebSocket），所以**两层 HTTP 共用这一份**。

三件和框架有关的事：

* ``dispatch`` 会把 WebSocket 的 scope 一起转发过来，所以应用必须两种协议都应答——
  只认 HTTP 的话，走错前缀的 WebSocket 会把连接挂住（见 ``plain.reject``）。
* 事件从 ``Fleet`` 来，而 ``Fleet`` 不认识本单元：依赖是单向的，所以这里在 ``@start`` 里
  订阅、在 ``@stop`` 里退订。
* 连接是本单元持有的资源，但**关掉它们不是本单元的事**：监听的 ``Server`` 依赖本单元，
  所以回收时 ``Server`` 先停（不再接新连接、关掉在途连接），本单元的 ``@stop`` 后跑。
  依赖顺序本身就是正确的停机顺序。

要让 ``ws://`` 真的握手成功，uvicorn 需要一个 WebSocket 实现（``websockets`` 或
``wsproto``）。``canary-framework[server]`` 只装 uvicorn 本身，所以这个依赖写在本项目的
``pyproject.toml`` 里。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from canary_framework import Canary, dep, init, start, stop

from relay.counters import Counters
from relay.fleet import Event, Fleet
from relay.plain import Receive, Scope, Send, reject
from relay.settings import EdgeSettings


class Subscriber:
    """One connected client: a bounded queue and the kinds it asked for.

    一个连上来的客户端：一个有界队列，外加它订阅的事件类型。队列满了丢最旧的——边缘的
    带宽有限，运维看的是现在发生了什么，不是半小时前的积压。
    """

    __slots__ = ("dropped", "only", "queue")

    def __init__(self, size: int) -> None:
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=size)
        self.only: set[str] | None = None
        self.dropped = 0

    def wants(self, event: Event) -> bool:
        return self.only is None or event.get("type") in self.only

    def offer(self, event: Event) -> None:
        """Enqueue *event* if this client asked for its kind.

        订阅了才入队——广播走这条路。
        """
        if self.wants(event):
            self.push(event)

    def push(self, event: Event) -> None:
        """Enqueue *event* without ever blocking the publisher, filter or not.

        不阻塞发布者地入队：满了就丢掉最旧的一条。控制消息（握手回执、订阅回执）走这条路，
        不受订阅过滤影响。
        """
        while True:
            try:
                self.queue.put_nowait(event)
                return
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()
                self.dropped += 1

    def finish(self) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(None)


class EventStream(Canary):
    """A live event feed over WebSocket, fed by ``Fleet``'s listener list.

    WebSocket 实时事件流。
    """

    config = dep(EdgeSettings)
    fleet = dep(Fleet)
    counters = dep(Counters)

    #: 服务器按这个前缀分发到本单元。
    path = "/ws/events"

    clients: set[Subscriber]

    @init
    def build(self) -> None:
        self.clients = set()

    @start
    async def subscribe(self) -> None:
        self._unlisten = self.fleet.listen(self.fanout)

    @stop
    async def release(self) -> None:
        self._unlisten()
        for client in list(self.clients):
            client.finish()

    def fanout(self, event: Event) -> None:
        """Hand one event to every client. Called by ``Fleet.publish``; never blocks.

        广播给每个客户端。由 ``Fleet.publish`` 调用，不阻塞。
        """
        for client in self.clients:
            before = client.dropped
            client.offer(event)
            if client.dropped != before:
                self.counters.incr("relay_stream_dropped_total", client.dropped - before)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket" or not _under(scope["path"], self.path):
            await reject(send, scope)
            return
        if (await receive()).get("type") != "websocket.connect":
            return
        await send({"type": "websocket.accept"})
        client = Subscriber(self.config.stream_queue_size)
        self.clients.add(client)
        self.counters.incr("relay_stream_clients_total")
        await _send_json(
            send,
            {
                "type": "hello",
                "site": self.config.site_id,
                "devices": self.fleet.summary(),
            },
        )
        pump = asyncio.create_task(self._pump(client, send))
        try:
            await self._read(client, receive)
        finally:
            client.finish()
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
            self.clients.discard(client)
            self.counters.incr("relay_stream_closed_total")

    async def _read(self, client: Subscriber, receive: Receive) -> None:
        """Read from the client until it goes away; it may narrow its subscription.

        读客户端，直到它断开。客户端可以用 ``{"only": ["device.event"]}`` 收窄订阅。
        """
        while True:
            message = await receive()
            kind = message.get("type")
            if kind == "websocket.disconnect":
                return
            if kind != "websocket.receive":
                continue
            command = _parse(message)
            if isinstance(command.get("only"), list):
                client.only = {str(item) for item in command["only"]}
                client.push({"type": "subscribed", "only": sorted(client.only)})

    async def _pump(self, client: Subscriber, send: Send) -> None:
        """Forward queued events to this client until it is finished.

        把队列里的事件送给客户端。
        """
        while True:
            event = await client.queue.get()
            if event is None:
                return
            await _send_json(send, event)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _parse(message: dict[str, Any]) -> dict[str, Any]:
    raw = message.get("text") or (message.get("bytes") or b"").decode(errors="replace")
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _send_json(send: Send, payload: dict[str, Any]) -> None:
    await send({"type": "websocket.send", "text": json.dumps(payload, ensure_ascii=False)})
