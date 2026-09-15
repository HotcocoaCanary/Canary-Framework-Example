"""The wire envelope shared by every endpoint.

``{code, data, msg}``：``code`` 为 0 表示成功，否则与 HTTP 状态行一致。两样都给，是为了
让只看 body 的客户端和只看状态码的网关都能判断结果。

失败信封由 ``app/wiring.py`` 的那一个异常处理器统一产出，handler 只描述成功形状。
"""

from pydantic import BaseModel, Field, computed_field


class R[T](BaseModel):
    code: int = Field(default=0, description="状态码: 0 = 成功, 4xx / 5xx = 失败")
    data: T | None = Field(default=None, description="响应数据")
    msg: str = Field(default="ok", description="消息")

    @classmethod
    def ok(cls, data: T | None = None, msg: str = "ok") -> "R[T]":
        return cls(code=0, data=data, msg=msg)

    @classmethod
    def fail(cls, msg: str = "error", code: int = 400) -> "R[None]":
        return R[None](code=code, data=None, msg=msg)


class PageResult[T](BaseModel):
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


class PageR[T](R[PageResult[T]]):
    """``R`` whose payload is one page of ``T``."""


def offset_of(page: int, size: int) -> int:
    """Translate a 1-based page number into a SQL ``OFFSET``."""
    return max(page - 1, 0) * max(size, 1)
