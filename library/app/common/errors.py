"""Domain errors — raised by services, turned into the envelope in one place.

服务层只 ``raise``，不认识任何 HTTP 概念。翻译成 ``{code, data, msg}`` 信封与状态码
的动作发生在 ``app/wiring.py::install_error_handlers``，全应用一处。

这是这次重写里少数"代码变简单了"的地方。0.9.x 的框架删掉 ``@on_request_error`` 之后，
异常只剩三条固定出路（绑定失败 422、``HTTPError`` 自带状态码、其余 500），领域异常
必须由每个 handler 自己用 ``await ok(...)`` 接住——漏写一个就变成 500，靠代码评审兜底。
换到 FastAPI 的 ``@app.exception_handler`` 之后，这条约束由框架保证，``ok()`` 这个
包装函数因此整个删掉了。
"""

from __future__ import annotations


class DomainError(Exception):
    """A rule violation the caller can act on — never a bug.

    ``code`` is the HTTP status the error deserves.
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
