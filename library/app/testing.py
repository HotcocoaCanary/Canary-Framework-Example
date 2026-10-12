"""Test helpers shipped with the package.

放在包里而不是 ``tests/conftest.py``，是为了两个场景都能有一个叫 ``tests/`` 的目录而
不在 import 时撞车。

启动一张图、按类型取单元、换替身，都用框架自带的 ``canary_framework.test``：
``running(LibraryApi, {AppConfig: AppConfig(...)})`` 与 ``unit(root, Database)``。这里只剩
图书馆业务自己的辅助函数。
"""

from __future__ import annotations

from datetime import timedelta

from canary_framework import asgi

from app.api import gateway
from app.infra.db import Database
from app.module.db.models import Loan, utcnow


def listener(stack: str) -> type[asgi.Server]:
    """A ``Gateway`` subclass of *stack* that lets the system pick the port.

    某一层 HTTP 的 ``Gateway`` 子类，端口交给系统分配。两个栈各有一个 ``Gateway``，因为
    ``dep()`` 是写在类上的声明——"听哪个应用"不能在运行期挑。
    """
    base = gateway(stack)
    return type(f"Test{base.__name__}", (base,), {"host": "127.0.0.1", "port": 0})


def paths_of(api: asgi.App) -> set[str]:
    """Every path this HTTP layer registered.

    这一层实际注册了哪些路径。两个栈的来源不一样，而这正是 ``asgi.web`` 的一个缺口：

    * FastAPI 版读 ``/openapi.json`` 的 ``paths``——公开、现成；
    * web 版只能读 ``canary_framework.asgi.web.router.collect()``，它**不是公开 API**。
      这个包不生成 OpenAPI，也没有别的办法问"你注册了哪些路径"。

    两边返回同一个集合，所以路由表的等价性可以直接断言。
    """
    if type(api).__module__.startswith("app.api.fastapi"):
        return set(api.app.openapi()["paths"])
    from canary_framework.asgi.web.router import collect

    return {path for path, _route, _call in collect(api)}


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
