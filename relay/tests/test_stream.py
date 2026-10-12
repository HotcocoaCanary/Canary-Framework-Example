"""WebSocket：真实握手、原生 ASGI 直调、背压。

三种粒度，各自能发现不同的东西：

* ``websockets`` 客户端 + ``port = 0``：握手、分发、uvicorn 的 ws 实现、优雅停机时连接
  怎么被关掉——这些只有真的监听了才测得到；
* 直接调用应用单元的 ``self.app``：不要服务器、不要网络，用一个假 channel 把 ASGI 消息
  喂进去。``asgi.App`` 的"应用"就是一个可调用对象，所以这种测法天然成立；
* 纯对象：``Subscriber`` 是普通类，背压策略单独测。
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from canary_framework.test import running, unit

from relay.clock import Clock
from relay.events import EventStream, Subscriber
from relay.fleet import Fleet
from relay.settings import EdgeSettings

# -- 真实套接字 -----------------------------------------------------------


async def test_a_client_gets_hello_then_live_events(relay, public) -> None:
    url = f"ws://127.0.0.1:{relay.public.port}/ws/events"
    async with websockets.connect(url) as ws:
        hello = json.loads(await ws.recv())
        assert hello == {"type": "hello", "site": "test-site", "devices": {}}

        await public.post("/devices/pos-1/heartbeat", json={"kind": "pos"})
        await public.post("/devices/pos-1/events", json={"kind": "paper_out"})

        first = json.loads(await ws.recv())
        second = json.loads(await ws.recv())
        assert first == {"type": "device.new", "device_id": "pos-1", "kind": "pos"}
        assert second["type"] == "device.event"
        assert second["kind"] == "paper_out"


async def test_a_client_can_narrow_its_subscription(relay, public) -> None:
    url = f"ws://127.0.0.1:{relay.public.port}/ws/events"
    async with websockets.connect(url) as ws:
        await ws.recv()  # hello
        await ws.send(json.dumps({"only": ["device.event"]}))
        assert json.loads(await ws.recv()) == {"type": "subscribed", "only": ["device.event"]}

        await public.post("/devices/pos-1/heartbeat", json={})  # device.new —— 被过滤掉
        await public.post("/devices/pos-1/events", json={"kind": "tamper"})
        received = json.loads(await ws.recv())
        assert received["type"] == "device.event"


async def test_the_stream_unit_tracks_its_clients(relay) -> None:
    stream = relay.public.stream
    assert stream.clients == set()
    async with websockets.connect(f"ws://127.0.0.1:{relay.public.port}/ws/events") as ws:
        await ws.recv()
        assert len(stream.clients) == 1
    for _ in range(20):  # 等服务器侧收到断开
        if not stream.clients:
            break
        await asyncio.sleep(0.05)
    assert stream.clients == set()
    assert relay.counters.value("relay_stream_clients_total") == 1
    assert relay.counters.value("relay_stream_closed_total") == 1


@pytest.mark.parametrize("path", ["/ws/nope", "/zzz"])
async def test_a_websocket_on_the_wrong_path_is_refused(relay, path: str) -> None:
    """走错前缀就握手失败。

    注意看到的是 **HTTP 403**，不是 ``dispatch`` 写的 close code 1008：按 ASGI 的规定，
    accept 之前关闭就是握手失败，uvicorn 把它变成 403，客户端拿不到那个 code。
    """
    with pytest.raises(websockets.exceptions.InvalidStatus) as caught:
        await websockets.connect(f"ws://127.0.0.1:{relay.public.port}{path}")
    assert caught.value.response.status_code == 403


async def test_stopping_the_process_closes_live_connections(relay) -> None:
    """优雅停机：``Server`` 先停，它关掉在途连接；之后才轮到它依赖的应用单元。"""
    ws = await websockets.connect(f"ws://127.0.0.1:{relay.public.port}/ws/events")
    await ws.recv()
    await asyncio.wait_for(relay.stop(), timeout=10)
    with pytest.raises(websockets.exceptions.ConnectionClosed):
        await asyncio.wait_for(ws.recv(), timeout=5)
    # @stop 之后订阅者列表也空了
    assert relay.public.stream.clients == set()


# -- 不要服务器，也不要网络 ------------------------------------------------


class Channel:
    """A fake ASGI channel: a queue in, a list out.

    假 channel：进来的消息排队，出去的消息记下来。
    """

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.sent: list[dict] = []

    async def receive(self) -> dict:
        return await self.incoming.get()

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    def push(self, message: dict) -> None:
        self.incoming.put_nowait(message)

    async def next_json(self) -> dict:
        for _ in range(100):
            for message in list(self.sent):
                if message["type"] == "websocket.send":
                    self.sent.remove(message)
                    return json.loads(message["text"])
            await asyncio.sleep(0.01)
        raise AssertionError(f"没有收到 websocket.send，只有 {self.sent}")


async def test_the_stream_application_can_be_driven_by_hand() -> None:
    """``asgi.App`` 的 ``self.app`` 就是一个可调用对象，测试可以自己当服务器。"""
    doubles = {EdgeSettings: EdgeSettings(site_id="bare"), Clock: Clock()}
    async with running(EventStream, doubles) as stream:
        fleet = unit(stream, Fleet)
        channel = Channel()
        scope = {"type": "websocket", "path": "/ws/events", "headers": []}
        served = asyncio.create_task(stream.app(scope, channel.receive, channel.send))

        channel.push({"type": "websocket.connect"})
        hello = await channel.next_json()
        assert {"type": "websocket.accept"} in channel.sent
        assert hello == {"type": "hello", "site": "bare", "devices": {}}

        fleet.record_event("pos-1", "tamper", {"door": "open"})
        event = await channel.next_json()
        assert (event["type"], event["kind"]) == ("device.event", "tamper")

        channel.push({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(served, timeout=5)
        assert stream.clients == set()


async def test_a_plain_http_request_to_the_stream_is_refused() -> None:
    """``dispatch`` 会把 HTTP 也转发进来，所以应用必须两种协议都应答。"""
    doubles = {EdgeSettings: EdgeSettings(), Clock: Clock()}
    async with running(EventStream, doubles) as stream:
        channel = Channel()
        await stream.app({"type": "http", "path": "/ws/events"}, channel.receive, channel.send)
        assert channel.sent[0]["status"] == 404


# -- 纯对象 ---------------------------------------------------------------


def test_a_slow_client_loses_the_oldest_events() -> None:
    """背压：队列满了丢最旧的，发布者永不阻塞。"""
    client = Subscriber(size=2)
    for index in range(5):
        client.offer({"type": "device.event", "n": index})
    assert client.dropped == 3
    assert [client.queue.get_nowait()["n"] for _ in range(2)] == [3, 4]


def test_a_filter_drops_without_counting_as_backpressure() -> None:
    client = Subscriber(size=2)
    client.only = {"device.event"}
    client.offer({"type": "device.new"})
    assert client.queue.empty()
    assert client.dropped == 0
