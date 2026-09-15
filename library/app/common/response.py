"""The wire envelope shared by every endpoint.

``code`` carries what Canary 0.9 cannot express: the framework always answers
``200 application/json`` (``web/core/routing.py:_to_response``), so the real
outcome of a request has to live inside the body.
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")


class R(BaseModel, Generic[T]):
    code: int = Field(default=0, description="状态码: 0 = 成功, 4xx / 5xx = 失败")
    data: Optional[T] = Field(default=None, description="响应数据")
    msg: str = Field(default="ok", description="消息")

    @classmethod
    def ok(cls, data: T = None, msg: str = "ok") -> "R[T]":
        return cls(code=0, data=data, msg=msg)

    @classmethod
    def fail(cls, msg: str = "error", code: int = 400) -> "R[None]":
        return R[None](code=code, data=None, msg=msg)


class PageResult(BaseModel, Generic[T]):
    records: list[T] = Field(default_factory=list, description="当前页数据")
    total: int = Field(default=0, description="总记录数")
    size: int = Field(default=20, description="每页大小")
    current: int = Field(default=1, description="当前页码 (1-based)")

    @computed_field
    @property
    def pages(self) -> int:
        return (self.total + self.size - 1) // self.size if self.size > 0 else 0

    @classmethod
    def of(cls, records: list[T], total: int, page: int, size: int) -> "PageResult[T]":
        return cls(records=records, total=total, size=size, current=page)


class PageR(R[PageResult[T]], Generic[T]):
    """``R`` whose payload is one page of ``T``."""


def offset_of(page: int, size: int) -> int:
    """Translate a 1-based page number into a SQL ``OFFSET``."""
    return max(page - 1, 0) * max(size, 1)
