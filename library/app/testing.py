"""Test helpers shipped with the package.

放在包里而不是 ``tests/conftest.py``，是为了两个场景都能有一个叫 ``tests/`` 的目录而
不在 import 时撞车。

启动一张图、按类型取单元、换替身，都用框架自带的 ``canary_framework.test``：
``running(LibraryApi, {AppConfig: AppConfig(...)})`` 与 ``unit(root, Database)``。这里只剩
图书馆业务自己的辅助函数。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from canary_framework import Canary
from canary_framework.test import running
from canary_framework.web.asgi import Application
from canary_framework.web.asgi.server import Server

from app.api import gateway, root_unit
from app.api import stack as stack_module
from app.infra.db import Database
from app.module.db.models import Loan, utcnow


@asynccontextmanager
async def running_stack(
    name: str, doubles: dict[Any, Any] | None = None
) -> AsyncIterator[tuple[Canary, Application]]:
    """Start one HTTP layer and yield ``(graph root, ASGI application)``.

    启动某一层，产出"图的根"与"ASGI 应用"两样东西。两层在这里的差别一眼能看见：

    * canary 层：应用单元自己就是根，**也**就是那个 ASGI 应用；
    * fastapi 层：根是 ``Services``（组合根单元），应用要用 ``create_app(root)`` 另外建，
      并且要把图挂到它身上（见 ``app/api/fastapi/bridge.py``）。

    没有服务器，也没有端口——两层都只是 ASGI 应用，``httpx.ASGITransport`` 直接打。
    """
    async with running(root_unit(name), doubles) as root:
        if name == "canary":
            yield root, root
        else:
            yield root, stack_module(name).create_app(root)


def listener(stack: str) -> type[Server]:
    """A ``Gateway`` subclass of *stack* that lets the system pick the port.

    某一层 HTTP 的 ``Gateway`` 子类，端口交给系统分配。两个栈各有一个 ``Gateway``，因为
    ``dep()`` 是写在类上的声明——"听哪个应用"不能在运行期挑。
    """
    base = gateway(stack)
    return type(f"Test{base.__name__}", (base,), {"host": "127.0.0.1", "port": 0})


def paths_of(name: str, root: Canary, app: Any) -> set[str]:
    """Every path this HTTP layer registered.

    这一层实际注册了哪些路径。两层的来源不一样，而这正是应用单元那边的一个缺口：

    * 原生 FastAPI：读 ``app.openapi()["paths"]``——公开、现成；
    * 应用单元：只能读 ``canary_framework.web.asgi.app.router.collect()``，它**不是公开
      API**（这个包不生成 OpenAPI，也没有别的办法问"你注册了哪些路径"）。

    两边返回同一个集合，所以路由表的等价性可以直接断言。
    """
    if name == "fastapi":
        return set(app.openapi()["paths"])
    from canary_framework.web.asgi.app.router import collect

    return {path for path, _route, _call in collect(root)}


def payload(response):
    """Unwrap ``R`` and assert the call succeeded."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def failure(response) -> tuple[int, str]:
    """Unwrap ``R`` and assert the call reported a domain failure.

    失败同时出现在状态行和信封里，两者必须一致——这由 ``LibraryApi`` 的那一个异常
    处理器保证。0.9.x 要靠每个 handler 自己记得 ``await ok(...)``，漏一个就变 500。
    """
    body = response.json()
    assert body["code"] != 0, body
    assert response.status_code == body["code"], response.text
    return body["code"], body["msg"]


async def make_book(client, **overrides) -> dict:
    request = {
        "title": "分布式系统：概念与设计",
        "author": "George Coulouris",
        "category": "计算机",
        "copies": 1,
    }
    request.update(overrides)
    return payload(await client.post("/api/catalog/books", json=request))


async def make_reader(client, **overrides) -> dict:
    request = {"name": "张三", "level": "normal"}
    request.update(overrides)
    return payload(await client.post("/api/readers/", json=request))


async def make_overdue(database: Database, loan_id: str, days: int) -> None:
    """Backdate a loan so that it is *days* days overdue, right now."""
    async with database.begin() as session:
        loan = await session.get(Loan, loan_id)
        shift = loan.due_at - (utcnow() - timedelta(days=days))
        loan.due_at -= shift
        loan.borrowed_at -= shift
        session.add(loan)
