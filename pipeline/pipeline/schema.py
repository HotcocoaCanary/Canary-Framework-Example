"""Request and response models for the intake.

接入口的请求与响应模型。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RowIn(BaseModel):
    account: str = Field(description="账号；空账号会被行级拒收")
    amount_cents: int = Field(description="金额（分）；0 会被行级拒收")
    ref: str = ""


class Batch(BaseModel):
    """One submitted statement batch."""

    source: str = Field(default="unknown", description="来源：bank-icbc / alipay …")
    lane: Literal["fast", "bulk"] | None = Field(
        default=None, description="留空则按行数自动选通道"
    )
    rows: list[RowIn] = Field(default_factory=list)


class JobView(BaseModel):
    """A job as the API shows it."""

    job_id: str
    source: str
    lane: str
    rows: int
    state: str
    attempts: int
    posted: int
    rejected: list[str]
    error: str | None


class Status(BaseModel):
    """What the operator and the load balancer want to know."""

    accepting: bool
    lanes: dict[str, dict[str, Any]]
    jobs: dict[str, int]
    ledger: dict[str, Any]
