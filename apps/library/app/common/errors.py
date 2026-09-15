"""Domain errors — raised by services, turned into the envelope by ``ok()``.

框架在 HEAD 上把 ``@on_request_error`` 删了，异常只剩三条固定出路：请求绑定失败
→ 422、``HTTPError`` → 它自带的状态码、其余任何异常 → JSON 500。理由写在
``web/core/app.py``：那三条都是**框架**层面的失败，而"预期内的业务失败"该由
handler 以返回值表达，不该抛出去让框架翻译。

本项目的对外契约是 ``{code, data, msg}`` 信封 + 与之一致的 HTTP 状态码，两样都要。
所以接住领域异常的地方回到应用自己手里，就在这个 :func:`ok`——每个 handler 本来
就要过它，它既是成功路径的信封，也是失败路径的边界：

- 成功：``R.ok(data)``，由框架按返回注解序列化。
- 失败：直接造一个 ``JSONResponse``，状态码取 ``DomainError.code``。框架的
  ``_to_response`` 对 ``Response`` 原样放行，所以状态码能真的落到状态行上。

代价是每个 handler 都必须记得 ``await ok(...)``——忘了写，领域异常就会变成 500。
0.9.3 的 ``@on_request_error`` 是全应用一处、不可能漏；现在这条约束靠代码评审。
换来的是框架少一个概念。

服务层照旧只 ``raise``，不认识任何 HTTP 概念。
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, TypeVar

from starlette.responses import JSONResponse, Response

from app.common.response import R

T = TypeVar("T")


class DomainError(Exception):
    """A rule violation the caller can act on — never a bug.

    ``code`` is the HTTP status the error deserves; :func:`ok` is the single
    place that applies it.
    """

    code = 400

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFoundError(DomainError):
    """The referenced entity does not exist."""

    code = 404


class ConflictError(DomainError):
    """The entity exists, but its current state forbids the operation."""

    code = 409


class ValidationError(DomainError):
    """The request is well-formed but semantically invalid."""

    code = 422


class PermissionError_(DomainError):
    """The caller may not perform this operation."""

    code = 403


async def ok(awaitable: Awaitable[T], envelope: type[R[Any]] = R) -> R[Any] | Response:
    """Await *awaitable*, wrapping the result — or the rule violation — in the envelope.

    成功走返回注解那条路（``R[T]``）；失败绕开注解，直接给出一个带状态码的
    ``JSONResponse``——文档上这个 handler 仍然只声明成功形状，这和 FastAPI 里
    ``response_model`` 只描述成功路径是同一个取舍。

    ``envelope`` 要和 handler 的返回注解同源：分页接口声明 ``-> PageR[X]``，
    这里就得给 ``PageR``。框架最终版会**按返回注解校验**返回值，而 ``R`` 的实例
    不是 ``PageR[X]`` 的实例——从前这个不一致一直存在，只是没人喊；
    现在它在第一次请求时就变成 500（见 doc/verification-final.md）。
    """
    try:
        return envelope.ok(await awaitable)
    except DomainError as error:
        return JSONResponse(
            R.fail(error.message, error.code).model_dump(mode="json"),
            status_code=error.code,
        )
