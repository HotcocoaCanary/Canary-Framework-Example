"""A batch, and the book that remembers what happened to it.

一批对账单，以及记着它后来怎么了的台账。``JobBook`` 是普通单元：它不碰 HTTP，也不碰
队列，接入口和消费者都读它，所以两边看到的是同一份状态。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from canary_framework import Canary

#: 任务状态：排队 → 处理中 → 完成 / 失败 / 被放弃（停机时在途、超过预算被取消）。
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
ABANDONED = "abandoned"


@dataclass(slots=True)
class Row:
    """One line of a statement.

    对账单的一行。
    """

    account: str
    amount_cents: int
    ref: str = ""


@dataclass(slots=True)
class Job:
    """One submitted batch.

    一批提交进来的流水。
    """

    job_id: str
    source: str
    lane: str
    rows: list[Row]
    state: str = QUEUED
    attempts: int = 0
    posted: int = 0
    rejected: list[str] = field(default_factory=list)
    error: str | None = None

    def view(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source": self.source,
            "lane": self.lane,
            "rows": len(self.rows),
            "state": self.state,
            "attempts": self.attempts,
            "posted": self.posted,
            "rejected": list(self.rejected),
            "error": self.error,
        }


class JobBook(Canary):
    """Every job this process has seen, and the id generator.

    本进程见过的全部任务。重启之后它还在——重启只重跑 ``@start`` / ``@stop``，单元本身
    不会被重建（见 README）。
    """

    jobs: dict[str, Job]

    def __init__(self) -> None:
        self.jobs = {}
        self._ids = itertools.count(1)

    def open(self, source: str, lane: str, rows: list[Row]) -> Job:
        job = Job(job_id=f"job-{next(self._ids):05d}", source=source, lane=lane, rows=rows)
        self.jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self.jobs.values())

    def states(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in self.jobs.values():
            counts[job.state] = counts.get(job.state, 0) + 1
        return counts
