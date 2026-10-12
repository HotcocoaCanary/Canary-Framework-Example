"""The native FastAPI layer —— a plain FastAPI application, served by our ``Server``.

第一层 HTTP：**原生 FastAPI**。模块级 ``APIRouter`` + 普通函数 + ``Depends``，加一座按类型
取单元的桥（``bridge.py``）。框架在这里只出一样东西：服务器单元在 ``@init`` 里把这个
FastAPI 对象赋给 ``self.app``——``Server`` 服务任何 ASGI 应用，不问出处。

接入口说"不"的三种方式（503 + ``Retry-After``、429、404）用的是和另一层**同一批领域异常**
（``queue.py`` 里的 ``QueueClosed`` / ``QueueFull``），只是落地方式不同：这边
``app.add_exception_handler(...)``，那边 ``@error(...)``。
"""

from __future__ import annotations

from typing import Annotated

from canary_framework import Canary, dep, init
from fastapi import APIRouter, FastAPI, Response
from fastapi.responses import JSONResponse

from pipeline import app as base
from pipeline.errors import UnknownJob, install_errors
from pipeline.gate import Gate
from pipeline.http.bridge import attach, use
from pipeline.jobs import JobBook, Row
from pipeline.journal import Journal
from pipeline.lanes import BulkLane, BulkQueue, FastLane, FastQueue
from pipeline.ledger import Ledger
from pipeline.queue import QueueClosed
from pipeline.schema import Batch, JobView, Status
from pipeline.settings import PipelineSettings

Config = Annotated[PipelineSettings, use(PipelineSettings)]
Intake = Annotated[Gate, use(Gate)]
Book = Annotated[JobBook, use(JobBook)]
Fast = Annotated[FastQueue, use(FastQueue)]
Bulk = Annotated[BulkQueue, use(BulkQueue)]
FastWorkers = Annotated[FastLane, use(FastLane)]
BulkWorkers = Annotated[BulkLane, use(BulkLane)]
Accounts = Annotated[Ledger, use(Ledger)]
Log = Annotated[Journal, use(Journal)]

batches = APIRouter(prefix="/batches", tags=["接入"])
status = APIRouter(prefix="/status", tags=["状态"])


@batches.post("", status_code=202)
async def submit(
    body: Batch, config: Config, gate: Intake, book: Book, fast: Fast, bulk: Bulk
) -> JobView:
    if not gate.accepting:
        raise QueueClosed("process is draining")
    lane = body.lane or ("bulk" if len(body.rows) > config.bulk_threshold else "fast")
    rows = [Row(account=row.account, amount_cents=row.amount_cents, ref=row.ref) for row in body.rows]
    job = book.open(body.source, lane, rows)
    (fast if lane == "fast" else bulk).submit(job)
    return JobView(**job.view())


@batches.get("")
async def listing(book: Book, state: str | None = None) -> list[JobView]:
    jobs = book.all()
    if state is not None:
        jobs = [job for job in jobs if job.state == state]
    return [JobView(**job.view()) for job in jobs]


@batches.get("/{job_id}")
async def one(job_id: str, book: Book) -> JobView:
    job = book.get(job_id)
    if job is None:
        raise UnknownJob(job_id)
    return JobView(**job.view())


def lane_view(lane: FastLane | BulkLane) -> dict[str, object]:
    return {
        "workers": lane.size,
        "queued": lane.queue.depth,
        "in_flight": dict(lane.in_flight),
        "done": lane.done,
        "drained": lane.drained,
        "left_behind": lane.queue.left_behind,
    }


@status.get("")
async def snapshot(
    gate: Intake, book: Book, ledger: Accounts, fast: FastWorkers, bulk: BulkWorkers
) -> Status:
    return Status(
        accepting=gate.accepting,
        lanes={lane.lane: lane_view(lane) for lane in (fast, bulk)},
        jobs=book.states(),
        ledger=ledger.summary(),
    )


@status.get("/health")
async def health(gate: Intake) -> Response:
    """``200`` while accepting, ``503`` once the gate is closed."""
    if gate.accepting:
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "draining"}, status_code=503)


@status.get("/journal")
async def steps(journal: Log) -> list[str]:
    """The lifecycle journal —— 两步停机留下的那几条。"""
    return list(journal.entries)


class Lanes(Canary):
    """The composition root for this layer —— 没有应用单元时，总得有人知道该启动谁。

    canary 层不需要它：应用单元就是根（``IngestApp`` 依赖两个路由单元，路由单元依赖通道与
    台账）。这一层的接口是模块级函数，图上没有任何东西指向它们，所以这个单元把该启动的都
    列出来。
    """

    config = dep(PipelineSettings)
    gate = dep(Gate)
    book = dep(JobBook)
    ledger = dep(Ledger)
    journal = dep(Journal)
    fast = dep(FastLane)
    bulk = dep(BulkLane)


def create_app(root: Canary) -> FastAPI:
    """Build the FastAPI application and attach it to a running graph."""
    app = FastAPI(title="对账单导入流水线", version="1.0.0")
    app.include_router(batches)
    app.include_router(status)
    install_errors(app)
    attach(app, root)
    return app


# -- 装配：监听的单元与根单元 ----------------------------------------------


class IngestServer(base.IngestServer):
    """它不依赖应用单元，而是依赖 ``Lanes``（这一层的组合根），应用在 ``@init`` 里赋进来。"""

    lanes = dep(Lanes)

    @init
    def build(self) -> None:
        self.app = create_app(self.lanes)


class Pipeline(base.Pipeline):
    server = dep(IngestServer)
