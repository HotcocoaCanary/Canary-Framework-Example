"""两步停机：关闸 → 排空 → 回收。

这是本场景存在的理由。``library`` 的停机是"ASGI lifespan 退出"，``telemetry`` 的停机是
"取消几个循环"；这里两件事同时成立——**在途的 HTTP 请求**和**在途的后台任务**要按不同的
顺序回收，而顺序必须是可断言的，不是"看起来没问题"。
"""

from __future__ import annotations

import asyncio

import httpx

from pipeline.http import root
from pipeline.jobs import ABANDONED, DONE
from pipeline.testing import rows, settle, started


async def test_the_journal_records_both_steps_in_order(pipe) -> None:
    """启动是依赖在前，停机是本单元在前——两个方向都在这份日志里。"""
    opened = list(pipe.journal.entries)
    # enter(serving)：依赖在前，所以两条通道先说话，根单元最后
    assert opened == [
        "serving: fast 通道 2 个消费者开始接活",
        "serving: bulk 通道 1 个消费者开始接活",
        "serving: 接入开放",
    ]

    await pipe.stop()
    steps = pipe.journal.entries[len(opened) :]
    # leave(serving)：本单元在前，所以根单元先关闸，之后才轮到通道排空
    assert steps[0] == "quiesce: 关闸（/status/health 开始回 503）"
    assert sorted(steps[1:3]) == [
        "quiesce: bulk 通道排空完成，剩 0 个",
        "quiesce: fast 通道排空完成，剩 0 个",
    ]
    # @stop 最后，而且是在 quiesce 全跑完之后
    assert all(step.startswith("stop:") for step in steps[3:])
    assert len(steps) == 5


async def test_in_flight_work_finishes_during_the_drain(stack) -> None:
    """停机时在途的任务做完才算停完——不是取消它。"""
    async with started(root(stack), row_seconds=0.01, drain_timeout_seconds=10.0) as pipe:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            job = (await client.post("/batches", json={"rows": rows(40)})).json()
            await asyncio.sleep(0.05)  # 让消费者接上
            assert pipe.fast.in_flight

        await pipe.stop()

    finished = pipe.book.get(job["job_id"])
    assert finished is not None
    assert finished.state == DONE
    assert finished.posted == 40
    assert pipe.fast.drained is True
    assert pipe.ledger.summary()["postings"] == 40


async def test_queued_work_is_drained_too(stack) -> None:
    """已经排上队、还没被接走的任务也要做完。"""
    async with started(root(stack), lane_workers={"fast": 1, "bulk": 1}, row_seconds=0.002) as pipe:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            submitted = [
                (await client.post("/batches", json={"rows": rows(5)})).json()["job_id"]
                for _ in range(6)
            ]
        await pipe.stop()

    assert [pipe.book.get(job_id).state for job_id in submitted] == [DONE] * 6
    assert pipe.fast.queue.left_behind == 0


async def test_new_work_is_refused_while_the_port_still_answers(stack) -> None:
    """关闸之后端口**还在监听**：新提交 503，查询照常，在途请求不受影响。

    这是两步停机对外的样子，也是它存在的理由——上游的负载均衡要先看到 503 把流量摘走，
    这期间进程还得把手上的活干完。``@stop``（真正关监听）在这之后才跑。
    """
    async with started(root(stack), row_seconds=0.02, drain_timeout_seconds=10.0) as pipe:
        base = f"http://127.0.0.1:{pipe.server.port}"
        async with httpx.AsyncClient(base_url=base) as client:
            job = (await client.post("/batches", json={"rows": rows(40)})).json()
            await asyncio.sleep(0.05)

            stopping = asyncio.create_task(pipe.stop())
            await asyncio.sleep(0.1)  # 第一步（关闸）已经跑完，第二步（排空）正在等

            refused = await client.post("/batches", json={"rows": rows(1)})
            assert refused.status_code == 503
            assert refused.headers["retry-after"] == "5"
            assert (await client.get("/status/health")).status_code == 503
            # 查询仍然可用，在途任务还在跑
            assert (await client.get(f"/batches/{job['job_id']}")).json()["state"] == "running"

            await stopping

        assert pipe.book.get(job["job_id"]).state == DONE


async def test_the_drain_gives_up_after_its_budget(stack) -> None:
    """预算用完就放弃：在途任务被取消，而且**说清楚**它的下场。

    放弃是停机的一部分，不是异常——所以任务的终态是 ``abandoned``，不是 ``failed``，
    日志里也写明排空超时。真实系统靠这个区分"该重投"和"该查原因"。
    """
    async with started(root(stack), row_seconds=0.05, drain_timeout_seconds=0.1) as pipe:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            # 显式指定通道：100 行默认会走 bulk，这里要压的是 fast
            job = (await client.post("/batches", json={"lane": "fast", "rows": rows(100)})).json()
            await asyncio.sleep(0.05)
        await pipe.stop()

    abandoned = pipe.book.get(job["job_id"])
    assert abandoned.state == ABANDONED
    assert "预算用完" in abandoned.error
    assert pipe.fast.drained is False
    assert [step for step in pipe.journal.entries if "排空超时" in step]


async def test_what_is_left_behind_is_counted(stack) -> None:
    """没人做的活在停机时被记下来——队列不是黑洞。"""
    async with started(root(stack), lane_workers={"fast": 0}, drain_timeout_seconds=0.05) as pipe:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            for _ in range(3):
                assert (await client.post("/batches", json={"rows": rows(1)})).status_code == 202
        await pipe.stop()

    assert pipe.fast.queue.left_behind == 3
    assert pipe.book.states() == {"queued": 3}


async def test_stop_is_idempotent(pipe) -> None:
    """重复 ``stop()`` 是空操作——``leave`` 的那一步也一样。"""
    await pipe.stop()
    entries = list(pipe.journal.entries)
    await pipe.stop()
    await pipe.stop()
    assert pipe.journal.entries == entries


async def test_restarting_keeps_the_ledger_and_rebuilds_the_queue(stack) -> None:
    """重启：``@start`` / ``@stop`` 再跑一遍，``@init`` 不再跑。

    所以"可回收的资源"（队列、消费者任务）放在 ``@start``，而"状态"（账本、台账）放在
    ``__init__``——重启不该丢账，但队列必须是新的。``@init`` 里建的东西两边都不是：它
    重启之后既不会被重建，也不会被回收，这是这个框架里最容易踩的一条。
    """
    async with started(root(stack), row_seconds=0.0) as pipe:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            first = (await client.post("/batches", json={"rows": rows(2)})).json()
            await settle(pipe, first["job_id"])
        # 这一层服务的那个 ASGI 应用：@init 建一次就不动。两层取法不同——canary 层是
        # "依赖即服务"（服务器上没有 app 属性），fastapi 层是 @init 里赋的 self.app。
        app_before = getattr(pipe.server, "app", None) or pipe.server.api
        first_queue = pipe.fast.queue.items
        await pipe.stop()

        assert pipe.fast.queue.closed is True
        assert pipe.gate.accepting is False

        # 再启动一次同一个根单元
        await pipe.start()

        assert pipe.gate.accepting is True           # @start 又跑了
        assert pipe.fast.queue.closed is False       # 队列是新建的
        assert pipe.fast.queue.items is not first_queue
        assert (getattr(pipe.server, "app", None) or pipe.server.api) is app_before
        assert pipe.ledger.summary()["postings"] == 2  # 账还在

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{pipe.server.port}") as client:
            second = (await client.post("/batches", json={"rows": rows(1)})).json()
            await settle(pipe, second["job_id"])
        assert pipe.ledger.summary()["postings"] == 3
        assert len([step for step in pipe.journal.entries if step == "serving: 接入开放"]) == 2
        await pipe.stop()
