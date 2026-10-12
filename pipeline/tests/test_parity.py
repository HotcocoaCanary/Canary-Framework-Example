"""两层 HTTP 的等价性：同一串请求，同一串答案。

这条流水线的状态是确定的（任务号 ``job-00001`` 递增、金额固定、没有时间戳进响应体），
所以两层的答案应当**一字不差**——除了校验失败的报文，那里有两处真差别（见最后一条）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from canary_framework.test import running, unit

from pipeline.http import NAMES, root
from pipeline.jobs import JobBook
from pipeline.testing import rows, settings

SCRIPT: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/status", None),
    ("GET", "/status/health", None),
    ("GET", "/batches", None),
    ("POST", "/batches", {"source": "bank-icbc", "rows": rows(3)}),
    ("GET", "/batches/job-00001", None),
    ("POST", "/batches", {"source": "alipay", "rows": rows(60)}),
    ("POST", "/batches", {"source": "bank-icbc", "lane": "bulk", "rows": rows(1)}),
    ("GET", "/batches", None),
    ("GET", "/batches?state=done", None),
    ("GET", "/status/journal", None),
    # 失败路径
    ("GET", "/batches/job-99999", None),
    ("POST", "/batches", {"source": "x", "lane": "express", "rows": []}),
    ("POST", "/batches", {"rows": [{"account": "1001", "amount_cents": "many"}]}),
    ("GET", "/nowhere", None),
]


def comparable(payload: Any) -> Any:
    """Drop the two fields in which the two layers' 422 bodies legitimately differ."""
    if isinstance(payload, dict):
        if {"loc", "msg", "type"} <= set(payload):
            return {"loc": payload["loc"], "type": payload["type"]}
        return {key: comparable(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [comparable(item) for item in payload]
    return payload


async def answers_of(stack: str) -> list[tuple[str, int, Any]]:
    """Run the script against one stack, waiting for the lanes to settle first."""
    async with running(root(stack), {type(settings()): settings(row_seconds=0.0)}) as pipe:
        url = f"http://127.0.0.1:{pipe.server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            answers: list[tuple[str, int, Any]] = []
            for method, path, body in SCRIPT:
                response = await client.request(method, path, json=body)
                answers.append(
                    (f"{method} {path}", response.status_code, comparable(response.json()))
                )
                await drain(pipe)  # 让后台把队列做空，下一条才看得到稳定的状态
            return answers


async def drain(pipe) -> None:
    """Wait until both lanes are idle, so the next answer is deterministic."""
    book = unit(pipe, JobBook)
    for _ in range(400):
        if not any(lane.queue.depth or lane.in_flight for lane in (pipe.fast, pipe.bulk)):
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"通道没有空下来: {book.states()}")


async def test_both_stacks_answer_the_same_script() -> None:
    """同一串请求，两层的状态码与响应体逐条相同。"""
    theirs = await answers_of("fastapi")
    ours = await answers_of("web")

    differences = [
        (step, left, right)
        for (step, *left), (_, *right) in zip(theirs, ours, strict=True)
        if left != right
    ]
    assert not differences, "\n".join(
        f"{step}\n  fastapi: {left}\n  web:     {right}" for step, left, right in differences
    )


async def test_the_two_layers_say_no_the_same_way() -> None:
    """接入口说"不"的三种方式在两层上一致：503 + Retry-After、429、404。

    这三条在 FastAPI 版是 ``app.add_exception_handler``，在 web 版是 ``@error`` 标记的方法，
    报文与响应头必须一样——上游的重试逻辑依赖它。
    """
    seen = {}
    for name in NAMES:
        async with running(
            root(name), {type(settings()): settings(lane_workers={"fast": 0}, queue_size=1)}
        ) as pipe:
            url = f"http://127.0.0.1:{pipe.server.port}"
            async with httpx.AsyncClient(base_url=url) as client:
                first = await client.post("/batches", json={"rows": rows(1)})
                full = await client.post("/batches", json={"rows": rows(1)})
                missing = await client.get("/batches/job-00009")
                pipe.gate.close()
                pipe.fast.queue.close()
                closed = await client.post("/batches", json={"rows": rows(1)})
                health = await client.get("/status/health")
                seen[name] = [
                    (first.status_code, full.status_code, missing.status_code),
                    (full.json(), missing.json(), closed.json()),
                    (closed.status_code, closed.headers.get("retry-after")),
                    (health.status_code, health.json()),
                ]
    assert seen["fastapi"] == seen["web"]
    assert seen["web"][2] == (503, "5")
    assert seen["web"][3] == (503, {"status": "draining"})
