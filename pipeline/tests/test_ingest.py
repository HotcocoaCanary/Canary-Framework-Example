"""接入与消费：提交进来、队列中转、记账出去。

HTTP 这一侧返回 202 就结束了，任务是后台做的，所以几乎每条测试都要"等它做完"。
``settle()`` 就是这件事——它读的是图上的单元，不是 HTTP。
"""

from __future__ import annotations

import asyncio

import pytest
from canary_framework.test import running, unit

from pipeline.http import root
from pipeline.jobs import DONE, JobBook, Row
from pipeline.ledger import AccountFrozen, Ledger, Rejected
from pipeline.processor import Processor
from pipeline.settings import PipelineSettings
from pipeline.testing import rows, settings, settle, started


async def test_a_batch_is_accepted_then_posted(pipe, client) -> None:
    response = await client.post("/batches", json={"source": "bank-icbc", "rows": rows(3)})
    assert response.status_code == 202
    body = response.json()
    assert (body["state"], body["lane"], body["rows"]) == ("queued", "fast", 3)

    done = await settle(pipe, body["job_id"])
    assert (done["state"], done["posted"], done["attempts"]) == ("done", 3, 1)
    assert pipe.ledger.summary()["postings"] == 3
    assert pipe.fast.done == 1


async def test_rows_can_be_rejected_without_failing_the_batch(pipe, client) -> None:
    """行级拒收和批级失败是两回事。"""
    payload = {
        "source": "alipay",
        "rows": [
            {"account": "1001", "amount_cents": 100},
            {"account": "", "amount_cents": 100},
            {"account": "1002", "amount_cents": 0},
        ],
    }
    body = (await client.post("/batches", json=payload)).json()
    done = await settle(pipe, body["job_id"])
    assert done["state"] == "done"
    assert done["posted"] == 1
    assert len(done["rejected"]) == 2


async def test_a_frozen_account_is_retried_to_the_limit(pipe, client) -> None:
    """可重试的失败重投，到上限才算失败——重投走的是同一条队列。"""
    pipe.ledger.freeze("1001")
    body = (await client.post("/batches", json={"rows": [{"account": "1001", "amount_cents": 5}]})).json()
    failed = await settle(pipe, body["job_id"])
    assert failed["state"] == "failed"
    assert failed["attempts"] == 3  # max_attempts
    assert "账户冻结" in failed["error"]


async def test_the_lane_is_chosen_by_size_unless_asked(pipe, client) -> None:
    small = (await client.post("/batches", json={"rows": rows(3)})).json()
    big = (await client.post("/batches", json={"rows": rows(60)})).json()
    forced = (await client.post("/batches", json={"lane": "bulk", "rows": rows(1)})).json()
    assert (small["lane"], big["lane"], forced["lane"]) == ("fast", "bulk", "bulk")

    for job in (small, big, forced):
        await settle(pipe, job["job_id"])
    assert pipe.fast.done == 1
    assert pipe.bulk.done == 2


async def test_two_lanes_are_two_instances_of_the_same_class(pipe) -> None:
    """"同一种东西的多个实例"在这个框架里就是"多个子类"。"""
    assert type(pipe.fast) is not type(pipe.bulk)
    assert isinstance(pipe.fast, type(pipe.bulk).__mro__[1])  # 共同的 WorkerPool
    assert pipe.fast.queue is not pipe.bulk.queue
    # 共享的叶子仍然只有一个实例
    assert pipe.fast.book is pipe.bulk.book
    assert pipe.fast.processor is pipe.bulk.processor


async def test_a_full_lane_answers_429(stack) -> None:
    """接入口不排无限长的队：通道满了就 429。"""
    async with started(root(stack), lane_workers={"fast": 0}, queue_size=1, drain_timeout_seconds=0.05) as pipe:
        import httpx

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            assert (await client.post("/batches", json={"rows": rows(1)})).status_code == 202
            full = await client.post("/batches", json={"rows": rows(1)})
            assert full.status_code == 429
            assert full.json()["detail"] == "lane is full"


async def test_unknown_jobs_are_404(client) -> None:
    missing = await client.get("/batches/job-99999")
    assert missing.status_code == 404
    assert missing.json()["job_id"] == "job-99999"


async def test_the_status_endpoint_reports_the_whole_process(pipe, client) -> None:
    body = (await client.post("/batches", json={"rows": rows(2)})).json()
    await settle(pipe, body["job_id"])

    status = (await client.get("/status")).json()
    assert status["accepting"] is True
    assert set(status["lanes"]) == {"fast", "bulk"}
    assert status["lanes"]["fast"]["workers"] == 2
    assert status["jobs"] == {"done": 1}
    assert status["ledger"]["postings"] == 2
    assert (await client.get("/status/health")).status_code == 200


# -- 不要服务器 -----------------------------------------------------------


async def test_the_application_alone_still_consumes(app_client) -> None:
    """没有 ``Server``，消费者照样在跑——它们是应用的依赖，不是服务器的。"""
    body = (await app_client.post("/batches", json={"rows": rows(2)})).json()
    assert body["state"] == "queued"
    for _ in range(200):
        job = (await app_client.get(f"/batches/{body['job_id']}")).json()
        if job["state"] == "done":
            break
        await asyncio.sleep(0.01)
    assert job["state"] == "done"
    assert (await app_client.get("/status")).json()["ledger"]["postings"] == 2


# -- 纯业务 ---------------------------------------------------------------


async def test_the_processor_can_be_tested_without_any_of_this() -> None:
    """``Processor`` 不认识队列也不认识 HTTP，所以直接 await 就测完了。"""
    async with running(Processor, {PipelineSettings: settings()}) as processor:
        ledger = unit(processor, Ledger)
        job = JobBook().open("test", "fast", [Row("1001", 100), Row("", 5)])
        await processor.run(job)
        assert (job.state, job.posted, len(job.rejected)) == (DONE, 1, 1)
        assert ledger.balances["1001"] == 100

        ledger.freeze("1001")
        with pytest.raises(AccountFrozen):
            await processor.run(job)


def test_the_ledger_is_a_plain_object() -> None:
    ledger = Ledger()
    ledger.post(Row("1001", 250, "x"))
    with pytest.raises(Rejected):
        ledger.post(Row("", 250))
    assert ledger.summary() == {"accounts": 1, "postings": 1, "frozen": [], "total_cents": 250}
