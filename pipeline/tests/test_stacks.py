"""两层各自独有的那一点东西。

这条流水线的 HTTP 很薄，所以两层的差别也就只有"有没有 OpenAPI"这一件。真正的差别在
``test_parity.py``（报文）与 ``library`` / ``relay`` 两个场景的 ``test_stack_*.py``（规则）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from canary_framework.test import running

from pipeline.http import root
from pipeline.testing import rows, settings


async def test_only_the_fastapi_layer_has_openapi() -> None:
    answers = {}
    for name in ("fastapi", "web"):
        async with running(root(name), {type(settings()): settings()}) as pipe:
            url = f"http://127.0.0.1:{pipe.server.port}"
            async with httpx.AsyncClient(base_url=url) as client:
                answers[name] = (
                    (await client.get("/openapi.json")).status_code,
                    (await client.get("/docs")).status_code,
                )
    assert answers["fastapi"] == (200, 200)
    assert answers["web"] == (404, 404)


async def test_the_openapi_document_covers_both_routers() -> None:
    async with running(root("fastapi"), {type(settings()): settings()}) as pipe:
        url = f"http://127.0.0.1:{pipe.server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            schema = (await client.get("/openapi.json")).json()
    assert {"/batches", "/batches/{job_id}", "/status", "/status/health"} <= set(schema["paths"])
    assert schema["info"]["title"] == "对账单导入流水线"


@pytest.mark.parametrize("stack", ["fastapi", "web"])
async def test_the_access_log_is_off_on_both(stack: str) -> None:
    """压测时访问日志会严重干扰结果，所以 ``IngestServer`` 带 ``access_log=False``。"""
    from pipeline.http import stack as stack_module

    assert stack_module(stack).IngestServer.__canary_server__["access_log"] is False


@pytest.mark.parametrize("stack", ["fastapi", "web"])
async def test_a_batch_survives_the_whole_round_trip(stack: str) -> None:
    """一条冒烟：两层都能提交、入队、记账。"""
    async with running(root(stack), {type(settings()): settings(row_seconds=0.0)}) as pipe:
        url = f"http://127.0.0.1:{pipe.server.port}"
        async with httpx.AsyncClient(base_url=url) as client:
            submitted = await client.post("/batches", json={"rows": rows(2)})
            assert submitted.status_code == 202
            job_id = submitted.json()["job_id"]
            for _ in range(200):
                job = (await client.get(f"/batches/{job_id}")).json()
                if job["state"] == "done":
                    break
                await asyncio.sleep(0.01)
            assert job["state"] == "done"
            assert pipe.ledger.summary()["postings"] == 2
