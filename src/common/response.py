from typing import Generic, TypeVar, Optional

from pydantic import BaseModel, Field

T = TypeVar("T")


class R(BaseModel, Generic[T]):
    code: int = Field(default=0, description="状态码: 0 = 成功, 1 / 4xx / 5xx = 失败")
    data: Optional[T] = Field(default=None, description="响应数据")
    msg: str = Field(default="ok", description="消息")

    @classmethod
    def ok(cls, data: T = None, msg: str = "ok") -> "R[T]":
        return cls(code=0, data=data, msg=msg)

    @classmethod
    def fail(cls, msg: str = "error", code: int = 1) -> "R[None]":
        return cls(code=code, data=None, msg=msg)


class PageResult(BaseModel, Generic[T]):
    records: list[T] = Field(description="当前页数据")
    total: int = Field(description="总记录数")
    size: int = Field(description="每页大小")
    current: int = Field(description="当前页码 (1-based)")
    pages: int = Field(description="总页数")


class PageR(R[PageResult[T]], Generic[T]):
    pass
