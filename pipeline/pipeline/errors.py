"""Domain errors and the one place they land.

领域异常与落地。接入口只 ``raise``，不认识状态码；``IngestApp`` 的 ``@init`` 把它们映射
到 HTTP 上，一处。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pipeline.queue import QueueClosed, QueueFull


class UnknownJob(Exception):
    """No such job id."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"unknown job: {job_id}")


def install_errors(app: FastAPI) -> None:
    """Map the three ways an intake can say no.

    接入口说"不"的三种方式。
    """

    async def closed(_: Request, error: Exception) -> JSONResponse:
        # 正在停机：503 + Retry-After，让上游换一个实例重试。
        return JSONResponse(
            {"detail": "intake closed", "reason": str(error)},
            status_code=503,
            headers={"retry-after": "5"},
        )

    async def full(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "lane is full", "reason": str(error)}, status_code=429)

    async def missing(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, UnknownJob)
        return JSONResponse({"detail": str(error), "job_id": error.job_id}, status_code=404)

    app.add_exception_handler(QueueClosed, closed)
    app.add_exception_handler(QueueFull, full)
    app.add_exception_handler(UnknownJob, missing)
