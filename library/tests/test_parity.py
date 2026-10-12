"""两层 HTTP 的等价性：同一串请求，同一串答案。

``conftest.py`` 的参数化让每个行为测试各跑两遍，但那只证明"两边都对"，不证明"两边一样"。
这个文件把同一串请求**按同样的顺序**打到两层上，逐条比对状态码与响应体——序列化、字段
顺序、信封、错误格式的差别都会在这里现形。

id 与时间戳按模式归一化（它们本来就每次不同），其余一个字节都不许差。
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from canary_framework import dep
from canary_framework.test import running

from app.api import NAMES
from app.testing import running_stack

#: ``bk_01hq…`` 这类 id、条码、卡号，以及 ISO 时间戳：两次运行本来就不同，比对前抹掉。
ID = re.compile(r"^[a-z]{2,6}_[0-9a-f]{12,}$")
BARCODE = re.compile(r"^[BL]\d*[0-9a-f]{6,}$")
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")

#: 一串有先后依赖的请求：先建书与读者，再借还、检索、问答。
#: ``{book}`` / ``{reader}`` / ``{loan}`` 由前面的回答填进来。
SCRIPT: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/health", None),
    ("GET", "/api/catalog/books", None),
    ("GET", "/api/catalog/categories", None),
    ("POST", "/api/catalog/books", {"title": "分布式系统", "author": "C", "category": "计算机", "copies": 2}),
    ("GET", "/api/catalog/books/{book}", None),
    ("GET", "/api/catalog/books?keyword=分布式&page=1&size=10", None),
    ("PATCH", "/api/catalog/books/{book}", {"category": "教材"}),
    ("POST", "/api/catalog/books/{book}/copies", {"count": 1, "location": "分馆"}),
    ("GET", "/api/catalog/books/{book}/copies", None),
    ("POST", "/api/readers/", {"name": "张三", "level": "normal"}),
    ("GET", "/api/readers/{reader}", None),
    ("GET", "/api/readers/?keyword=张", None),
    ("POST", "/api/circulation/borrow", {"book_id": "{book}", "reader_id": "{reader}"}),
    ("GET", "/api/circulation/readers/{reader}/loans", None),
    ("POST", "/api/circulation/loans/{loan}/renew", None),
    ("POST", "/api/circulation/return", {"loan_id": "{loan}"}),
    ("GET", "/api/circulation/overdue", None),
    ("POST", "/api/rag/documents", {"title": "借阅规则", "text": "普通读者可借 5 本，借期 30 天。", "source": "手册"}),
    ("GET", "/api/rag/search?q=借期多久&top_k=3", None),
    ("POST", "/api/assistant/ask", {"question": "普通读者能借几本书？"}),
    # 失败路径：两层的错误格式也必须一样
    ("GET", "/api/catalog/books/bk_does_not_exist", None),
    ("GET", "/api/nowhere", None),
    ("POST", "/api/catalog/books", {"title": "缺作者"}),
    ("POST", "/api/catalog/books", {"title": "重复", "author": "x", "isbn": None}),
    ("PATCH", "/api/catalog/books/{book}", {}),
    ("POST", "/api/circulation/borrow", {"book_id": "bk_nope", "reader_id": "rd_nope"}),
]


def normalise(value: Any) -> Any:
    """Replace ids and timestamps, which differ between any two runs."""
    if isinstance(value, dict):
        # ``input`` 只有 FastAPI 的校验错误里有——唯一的真差别，单独一条测试钉着，
        # 不让它把整串比对都染红。
        return {key: normalise(item) for key, item in value.items() if key != "input"}
    if isinstance(value, list):
        return [normalise(item) for item in value]
    if isinstance(value, str):
        if ID.match(value) or BARCODE.match(value):
            return "<id>"
        if TIME.match(value):
            return "<time>"
    return value


def fill(text: str, seen: dict[str, str]) -> str:
    for name, value in seen.items():
        text = text.replace("{" + name + "}", value)
    return text


def remember(step: str, body: Any, seen: dict[str, str]) -> None:
    """Keep the ids the next steps need."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return
    if step.endswith("/api/catalog/books") and "id" in data:
        seen.setdefault("book", data["id"])
    elif step.endswith("/api/readers/") and "id" in data:
        seen.setdefault("reader", data["id"])
    elif step.endswith("/api/circulation/borrow") and "id" in data:
        seen.setdefault("loan", data["id"])


async def play(client: httpx.AsyncClient) -> list[tuple[str, int, Any]]:
    """Run the script and return what came back, normalised."""
    seen: dict[str, str] = {}
    answers: list[tuple[str, int, Any]] = []
    for method, raw_path, raw_body in SCRIPT:
        path = fill(raw_path, seen)
        body = raw_body
        if isinstance(raw_body, dict):
            body = {
                key: fill(value, seen) if isinstance(value, str) else value
                for key, value in raw_body.items()
            }
        response = await client.request(method, path, json=body)
        parsed = response.json() if response.content else None
        remember(raw_path, parsed, seen)
        answers.append((f"{method} {raw_path}", response.status_code, normalise(parsed)))
    return answers


async def test_both_stacks_answer_the_same_script() -> None:
    """同一串请求，两层的状态码与响应体逐条相同。"""
    async with (
        running_stack("fastapi") as (_fr, fastapi_app),
        running_stack("canary") as (_cr, canary_app),
    ):
        native = httpx.ASGITransport(app=fastapi_app, raise_app_exceptions=False)
        ours = httpx.ASGITransport(app=canary_app, raise_app_exceptions=False)
        async with (
            httpx.AsyncClient(transport=native, base_url="http://a") as a,
            httpx.AsyncClient(transport=ours, base_url="http://b") as b,
        ):
            native_answers = await play(a)
            our_answers = await play(b)

    assert len(native_answers) == len(SCRIPT)
    differences = [
        (step, left, right)
        for (step, *left), (_, *right) in zip(native_answers, our_answers, strict=True)
        if left != right
    ]
    assert not differences, "\n".join(
        f"{step}\n  fastapi: {left}\n  canary:  {right}" for step, left, right in differences
    )


async def test_the_validation_error_bodies_differ_by_one_field() -> None:
    """**【差异】** 校验失败的报文：两层只差一个 ``input`` 字段。

    ``asgi.web`` 的 422 刻意按 FastAPI 的形状来（``{"detail": [{"loc", "msg", "type"}]}``），
    但它调 pydantic 的 ``errors(include_input=False)``，所以**没有** ``input``——FastAPI
    那边是有的，里面是被拒的那份输入。

    影响：拿 ``input`` 做提示的前端、按整条 ``detail`` 做快照断言的测试，换一层就得改。
    期望要么跟 FastAPI 一致，要么文档里明说这一条，而不是只给一个"看起来一样"的例子。
    """
    async with (
        running_stack("fastapi") as (_fr, fastapi_app),
        running_stack("canary") as (_cr, canary_app),
    ):
        native = httpx.ASGITransport(app=fastapi_app, raise_app_exceptions=False)
        ours = httpx.ASGITransport(app=canary_app, raise_app_exceptions=False)
        async with (
            httpx.AsyncClient(transport=native, base_url="http://a") as a,
            httpx.AsyncClient(transport=ours, base_url="http://b") as b,
        ):
            broken = {"title": "缺作者"}
            native_error = (await a.post("/api/catalog/books", json=broken)).json()["detail"][0]
            our_error = (await b.post("/api/catalog/books", json=broken)).json()["detail"][0]

    assert set(native_error) == {"type", "loc", "msg", "input"}
    assert set(our_error) == {"type", "loc", "msg"}
    assert {key: native_error[key] for key in our_error} == our_error  # 其余三项一模一样


# -- 同步接口方法：两层都放进线程池 ------------------------------------------


def _sync_probe(stack: str):
    """An ASGI application with one **synchronous** blocking endpoint and one ``async`` one.

    两层各写一遍：一边是原生 FastAPI 的模块级函数，一边是应用单元的方法。
    """
    if stack == "fastapi":
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/probe/slow")
        def slow() -> dict:
            time.sleep(0.3)
            return {"ok": True}

        @app.get("/probe/fast")
        async def fast() -> dict:
            return {"ok": True}

        return app

    from canary_framework.web.asgi.app import App, Router, get

    class Probe(Router, prefix="/probe"):
        @get("/slow")
        def slow(self) -> dict:
            time.sleep(0.3)  # 一个同步阻塞调用：老的 DB 驱动、requests、文件 IO 都长这样
            return {"ok": True}

        @get("/fast")
        async def fast(self) -> dict:
            return {"ok": True}

    return type("Probed", (App,), {"probe": dep(Probe)})


async def _four_at_once(stack: str) -> float:
    """How long four concurrent calls to the blocking endpoint take."""
    probe = _sync_probe(stack)
    async with _probe_app(stack, probe) as app, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        began = time.monotonic()
        await asyncio.gather(*(client.get("/probe/slow") for _ in range(4)))
        return time.monotonic() - began


@asynccontextmanager
async def _probe_app(stack: str, probe):
    """A started probe application —— 应用单元要先启动，FastAPI 应用拿来就用。"""
    if stack == "fastapi":
        yield probe
        return
    async with running(probe) as unit_app:
        yield unit_app


async def _finish_order(stack: str) -> list[str]:
    """Which answers come back first when a blocking call is in flight."""
    probe = _sync_probe(stack)
    done: list[str] = []
    async with _probe_app(stack, probe) as app, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def hit(path: str) -> None:
            await client.get(path)
            done.append(path)

        slow = asyncio.create_task(hit("/probe/slow"))
        await asyncio.sleep(0.05)  # 事件循环没被占住的话，这一句会按时回来
        await hit("/probe/fast")
        await slow
    return done


async def test_a_synchronous_endpoint_runs_in_a_thread_on_both_layers() -> None:
    """同步的接口方法在两层上都进线程池：四个并发各阻塞 0.3s，总共还是 ~0.3s。

    FastAPI 一直是这样（普通 ``def`` 进线程池）；应用单元那层是这一轮才改的——之前它直接
    在事件循环里调同步方法，于是同步接口里的阻塞调用（老的同步 DB 驱动、``requests``、
    文件 IO）会卡住**整个进程**，连 ``/health`` 都答不出来。

    代价两层一样：线程池里的方法与事件循环并发运行，读写单元上的状态要自己保证线程安全
    ——本项目的接口方法都是 ``async def``，这一条不碰。
    """
    for name in NAMES:
        elapsed = await _four_at_once(name)
        assert elapsed < 0.8, f"{name}: 四个并发的同步接口用了 {elapsed:.2f}s，像是在排队"


async def test_a_blocking_endpoint_does_not_hold_up_the_event_loop() -> None:
    """阻塞的同步接口在途时，``async def`` 的接口照常应答——两层都是。

    这是上一条的另一半，而且比计时更硬：如果同步方法占住了事件循环，``/probe/fast``
    不可能先返回。
    """
    for name in NAMES:
        assert await _finish_order(name) == ["/probe/fast", "/probe/slow"], name
