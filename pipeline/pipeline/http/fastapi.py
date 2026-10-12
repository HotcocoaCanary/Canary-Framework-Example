"""The FastAPI layer —— the intake, and the units that listen.

第一层 HTTP：``canary_framework.asgi.fastapi``。和 ``web.py`` 逐行对照，差别只有四处：
导入的包、``tags``、成功状态码的关键字（``status_code=`` / ``status=``）、以及领域异常的
落地方式（``app.add_exception_handler`` / ``@error`` 标记）。

接入口说"不"有三种：闸门关了（停机中，503 + ``Retry-After``）、通道满了（429）、任务号
不存在（404）。前两种是 ``queue.py`` 里的领域异常——它们在**业务层**抛出，两层各自落地。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.asgi.fastapi import App, Router, get, post
from fastapi import Response
from fastapi.responses import JSONResponse

from pipeline import app as base
from pipeline.errors import UnknownJob, install_errors
from pipeline.gate import Gate
from pipeline.jobs import JobBook, Row
from pipeline.journal import Journal
from pipeline.lanes import BulkLane, BulkQueue, FastLane, FastQueue
from pipeline.ledger import Ledger
from pipeline.queue import QueueClosed
from pipeline.schema import Batch, JobView, Status
from pipeline.settings import PipelineSettings


class BatchApi(Router, prefix="/batches", tags=["接入"]):
    """Submit a batch, ask about a batch.

    提交一批、查一批。提交进来就入队返回 202，不等它做完。
    """

    config = dep(PipelineSettings)
    gate = dep(Gate)
    book = dep(JobBook)
    fast = dep(FastQueue)
    bulk = dep(BulkQueue)

    @post("", status_code=202)
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


class StatusApi(Router, prefix="/status", tags=["状态"]):
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
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "draining"}, status_code=503)

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


class IngestApp(App, title="对账单导入流水线", version="1.0.0"):
    """``/batches`` 与 ``/status``。"""

    batches = dep(BatchApi)
    status = dep(StatusApi)

    @init
    def setup(self) -> None:
        install_errors(self.app)


# -- 装配：监听的单元与根单元 ----------------------------------------------


class IngestServer(base.IngestServer):
    api = dep(IngestApp)


class Pipeline(base.Pipeline):
    server = dep(IngestServer)
