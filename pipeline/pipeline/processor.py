"""Processing one batch.

处理一批流水。它是纯业务：不认识队列，也不认识 HTTP，所以测试里直接
``await processor.run(job)`` 就能测完。
"""

from __future__ import annotations

import asyncio

from canary_framework import Canary, dep

from pipeline.jobs import DONE, Job
from pipeline.ledger import AccountFrozen, Ledger, Rejected
from pipeline.settings import PipelineSettings


class Processor(Canary):
    """Posts a batch into the ledger, row by row.

    一行一行记账。
    """

    config = dep(PipelineSettings)
    ledger = dep(Ledger)

    async def run(self, job: Job) -> Job:
        """Post every row. Row-level rejects are recorded; a frozen account aborts the batch.

        行级拒收记下来继续；账户冻结则整批中止（由调用方决定要不要重投）。
        """
        job.attempts += 1
        job.posted = 0
        job.rejected = []
        for row in job.rows:
            if self.config.row_seconds:
                await asyncio.sleep(self.config.row_seconds)
            try:
                self.ledger.post(row)
            except Rejected as exc:
                job.rejected.append(str(exc))
            except AccountFrozen:
                raise
            else:
                job.posted += 1
        job.state = DONE
        job.error = None
        return job
