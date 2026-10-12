"""The Canary layer —— the intake as units.

第二层 HTTP：``canary_framework.web.asgi.app``。路由是单元（``gate = dep(Gate)`` 写在类
上），应用单元**自己就是 ASGI 应用**，所以 ``IngestServer`` 只要 ``dep(IngestApp)``。

和 ``fastapi.py``（一个原生 FastAPI 应用）比：那边的接口是模块级函数，要用 ``Depends``
加一座按类型取单元的桥；领域异常那边是 ``app.add_exception_handler(...)``，这边是
``@error(...)`` 标记应用单元的方法。接口的**函数体两边一个字都不差**——它们本来就只是在
碰业务单元。
"""

from __future__ import annotations

from canary_framework import dep
from canary_framework.web.asgi.app import App, Request, Response, Router, error, get, post

from pipeline import app as base
from pipeline.errors import UnknownJob
from pipeline.gate import Gate
from pipeline.jobs import JobBook, Row
from pipeline.journal import Journal
from pipeline.lanes import BulkLane, BulkQueue, FastLane, FastQueue
from pipeline.ledger import Ledger
from pipeline.queue import QueueClosed, QueueFull
from pipeline.schema import Batch, JobView, Status
from pipeline.settings import PipelineSettings


class BatchApi(Router, prefix="/batches"):
    """Submit a batch, ask about a batch."""

    config = dep(PipelineSettings)
    gate = dep(Gate)
    book = dep(JobBook)
    fast = dep(FastQueue)
    bulk = dep(BulkQueue)

    @post("", status=202)
    async def submit(self, body: Batch) -> JobView:
        if not self.gate.accepting:
            raise QueueClosed("process is draining")
        lane = body.lane or ("bulk" if len(body.rows) > self.config.bulk_threshold else "fast")
        rows = [Row(account=row.account, amount_cents=row.amount_cents, ref=row.ref) for row in body.rows]
        job = self.book.open(body.source, lane, rows)
        self.queue_for(lane).submit(job)
        return JobView(**job.view())

    @get("")
    async def listing(self, state: str | None = None) -> list[JobView]:
        jobs = self.book.all()
        if state is not None:
            jobs = [job for job in jobs if job.state == state]
        return [JobView(**job.view()) for job in jobs]

    @get("/{job_id}")
    async def one(self, job_id: str) -> JobView:
        job = self.book.get(job_id)
        if job is None:
            raise UnknownJob(job_id)
        return JobView(**job.view())

    def queue_for(self, lane: str):
        """Pick the lane's queue —— 两条通道是两个单元，不是一个带名字的实例表。"""
        return self.fast if lane == "fast" else self.bulk


class StatusApi(Router, prefix="/status"):
    """Queue depth, lanes, jobs, ledger —— 以及给 LB 的那个 503。"""

    gate = dep(Gate)
    book = dep(JobBook)
    ledger = dep(Ledger)
    journal = dep(Journal)
    fast = dep(FastLane)
    bulk = dep(BulkLane)

    @get("")
    async def status(self) -> Status:
        return Status(
            accepting=self.gate.accepting,
            lanes={lane.lane: self.lane_view(lane) for lane in (self.fast, self.bulk)},
            jobs=self.book.states(),
            ledger=self.ledger.summary(),
        )

    @get("/health")
    async def health(self) -> Response:
        """``200`` while accepting, ``503`` once the gate is closed."""
        if self.gate.accepting:
            return Response.json({"status": "ok"})
        return Response.json({"status": "draining"}, status=503)

    @get("/journal")
    async def steps(self) -> list[str]:
        """The lifecycle journal —— 两步停机留下的那几条。"""
        return list(self.journal.entries)

    def lane_view(self, lane: FastLane | BulkLane) -> dict[str, object]:
        return {
            "workers": lane.size,
            "queued": lane.queue.depth,
            "in_flight": dict(lane.in_flight),
            "done": lane.done,
            "drained": lane.drained,
            "left_behind": lane.queue.left_behind,
        }


class IngestApp(App):
    """``/batches`` 与 ``/status``，外加接入口说"不"的三种方式。"""

    batches = dep(BatchApi)
    status = dep(StatusApi)

    @error(QueueClosed)
    async def closed(self, _: Request, exc: QueueClosed) -> Response:
        # 正在停机：503 + Retry-After，让上游换一个实例重试。
        return Response.json(
            {"detail": "intake closed", "reason": str(exc)},
            status=503,
            headers={"retry-after": "5"},
        )

    @error(QueueFull)
    async def full(self, _: Request, exc: QueueFull) -> Response:
        return Response.json({"detail": "lane is full", "reason": str(exc)}, status=429)

    @error(UnknownJob)
    async def missing(self, _: Request, exc: UnknownJob) -> Response:
        return Response.json({"detail": str(exc), "job_id": exc.job_id}, status=404)


# -- 装配：监听的单元与根单元 ----------------------------------------------


class IngestServer(base.IngestServer):
    api = dep(IngestApp)


class Pipeline(base.Pipeline):
    server = dep(IngestServer)
