"""两层 HTTP 的等价性：同一串请求，同一串答案。

``conftest.py`` 的参数化让每个行为测试各跑两遍，但那只证明"两边都对"，不证明"两边一样"。
这个文件把同一串请求按同样的顺序打到两层上，逐条比对状态码与响应体。

这个场景里时间是 ``ManualClock``、站点名固定、计数从零开始，所以响应体应当**一字不差**
——除了校验失败的报文：那里两层有两处真差别，由本文件最后一条测试单独钉着。
"""

from __future__ import annotations

from typing import Any

import httpx
from canary_framework.test import running

from relay.clock import Clock
from relay.http import NAMES, root
from relay.settings import AdminSettings, EdgeSettings
from relay.testing import ManualClock

TOKEN = "test-token"

#: 一串有先后依赖的请求：先心跳建设备，再事件、查询、隔离、巡检，最后几条失败路径。
SCRIPT: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/health", None),
    ("GET", "/devices", None),
    ("POST", "/devices/pos-1/heartbeat", {"kind": "pos", "metrics": {"paper": 0.8}}),
    ("POST", "/devices/pos-1/heartbeat", {"kind": "pos", "metrics": {"paper": 0.7}}),
    ("POST", "/devices/scale-7/heartbeat", {"kind": "scale"}),
    ("POST", "/devices/pos-1/events", {"kind": "paper_out", "payload": {"tray": 1}}),
    ("GET", "/devices", None),
    ("GET", "/devices?status=online", None),
    ("GET", "/devices/pos-1", None),
    ("GET", "/health", None),
    # 失败路径
    ("GET", "/devices/ghost", None),
    ("POST", "/devices/ghost/events", {"kind": "tamper"}),
    ("POST", "/devices/pos-1/heartbeat", {"kind": 7, "metrics": "nope"}),
    ("GET", "/nowhere", None),
]

#: 管理端口上的请求，都带口令。
ADMIN_SCRIPT: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/admin/health", None),
    ("GET", "/admin/fleet", None),
    ("POST", "/admin/fleet/pos-1/quarantine", None),
    ("GET", "/admin/fleet", None),
    ("POST", "/admin/fleet/pos-1/quarantine?on=false", None),
    ("GET", "/admin/fleet/pos-1/events", None),
    ("POST", "/admin/fleet/sweep", None),
    ("GET", "/admin/fleet/ghost/events", None),
    ("GET", "/", None),
    ("GET", "/metrics", None),
]


def comparable(payload: Any) -> Any:
    """Drop the two fields in which the two layers' 422 bodies legitimately differ.

    校验失败的报文里有两处真差别（见本文件最后一条测试）：``input`` 只有 FastAPI 有，
    ``msg`` 的措辞因为"校验 JSON 字节"与"校验已解析的对象"而不同。比对整串答案时把这两样
    抹掉，只留 ``loc`` 与 ``type``——它们必须一致，否则客户端的分支就会错。
    """
    if isinstance(payload, dict):
        if {"loc", "msg", "type"} <= set(payload):
            return {"loc": payload["loc"], "type": payload["type"]}
        return {key: comparable(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [comparable(item) for item in payload]
    return payload


async def play(
    client: httpx.AsyncClient, script: list[tuple[str, str, dict[str, Any] | None]]
) -> list[tuple[str, int, Any]]:
    answers: list[tuple[str, int, Any]] = []
    for method, path, body in script:
        response = await client.request(method, path, json=body)
        kind = response.headers.get("content-type", "")
        payload: Any
        if not response.content:
            payload = None
        elif kind.startswith("application/json"):
            payload = response.json()
        else:
            payload = response.text
        answers.append((f"{method} {path}", response.status_code, comparable(payload)))
    return answers


def doubles() -> dict:
    return {
        EdgeSettings: EdgeSettings(
            host="127.0.0.1", port=0, site_id="test-site", sweep_interval_seconds=3600.0
        ),
        AdminSettings: AdminSettings(host="127.0.0.1", port=0, token=TOKEN),
        Clock: ManualClock(),
    }


async def answers_of(stack: str) -> list[tuple[str, int, Any]]:
    """Run both scripts against one stack."""
    async with running(root(stack), doubles()) as relay:
        public_url = f"http://127.0.0.1:{relay.public.port}"
        admin_url = f"http://127.0.0.1:{relay.admin.port}"
        async with (
            httpx.AsyncClient(base_url=public_url) as public,
            httpx.AsyncClient(base_url=admin_url, headers={"x-admin-token": TOKEN}) as admin,
        ):
            return await play(public, SCRIPT) + await play(admin, ADMIN_SCRIPT)


async def test_both_stacks_answer_the_same_script() -> None:
    """同一串请求，两层的状态码与响应体逐条相同——包括 ``/metrics`` 的那段文本。"""
    theirs = await answers_of("fastapi")
    ours = await answers_of("canary")

    differences = [
        (step, left, right)
        for (step, *left), (_, *right) in zip(theirs, ours, strict=True)
        if left != right
    ]
    assert not differences, "\n".join(
        f"{step}\n  fastapi: {left}\n  canary:  {right}" for step, left, right in differences
    )


async def test_both_stacks_refuse_the_admin_port_without_the_token() -> None:
    """口令中间件是共用的那一份 ASGI 中间件，所以两层的 403 必须一模一样。"""
    seen = []
    for name in NAMES:
        async with running(root(name), doubles()) as relay:
            url = f"http://127.0.0.1:{relay.admin.port}"
            async with httpx.AsyncClient(base_url=url) as naked:
                answer = await naked.get("/admin/fleet")
                seen.append((answer.status_code, answer.json()))
    assert seen[0] == seen[1] == (403, {"detail": "forbidden"})


async def test_the_validation_error_bodies_differ_in_two_ways() -> None:
    """**【差异】** 校验失败的报文：两层差一个字段，还差一句措辞。两处都是有意的。

    1. ``input`` 只有 FastAPI 的错误里有（被拒的那份输入）。``asgi.web`` 调 pydantic 的
       ``errors(include_input=False)``，所以没有。
    2. ``msg`` 的措辞不同：FastAPI 把请求体解析成 Python 对象再校验
       （``validate_python``），应用单元那层直接校验**原始 JSON 字节**
       （``validate_json``）。于是同一个 ``dict_type`` 错误，一边说
       "Input should be a valid dictionary"，另一边说 "Input should be an object"。

    第 2 点是应用单元那一层的选择，``web.md`` 里写明了："请求体用的是 pydantic 的 JSON
    模式，直接校验原始字节，所以 ``strict=True`` 的模型也接受 JSON 里的日期、UUID 这类
    字符串。"普通模型两种模式的接受/拒绝是一致的，差的只是 ``msg`` 的措辞。

    ``loc`` 与 ``type`` 也一致，所以按 ``type`` 做分支的客户端不受影响；拿 ``msg`` 或
    ``input`` 直接显示给用户的前端换层时要改。
    """
    broken = {"kind": 7, "metrics": "nope"}
    bodies = {}
    for name in NAMES:
        async with running(root(name), doubles()) as relay:
            url = f"http://127.0.0.1:{relay.public.port}"
            async with httpx.AsyncClient(base_url=url) as http:
                answer = await http.post("/devices/pos-1/heartbeat", json=broken)
                assert answer.status_code == 422
                bodies[name] = answer.json()["detail"]

    theirs, ours = bodies["fastapi"], bodies["canary"]
    assert [(e["loc"], e["type"]) for e in theirs] == [(e["loc"], e["type"]) for e in ours]
    assert all("input" in e for e in theirs)
    assert not any("input" in e for e in ours)
    assert [e["msg"] for e in theirs] == [
        "Input should be a valid string",
        "Input should be a valid dictionary",
    ]
    assert [e["msg"] for e in ours] == [
        "Input should be a valid string",
        "Input should be an object",  # ← JSON 模式的措辞
    ]
