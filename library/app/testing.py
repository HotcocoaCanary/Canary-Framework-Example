"""Test helpers shipped with the package.

放在包里而不是 ``tests/conftest.py``，是为了两个场景都能有一个叫 ``tests/`` 的目录而
不在 import 时撞车。

替换单元用框架自带的 ``Scope.provide``：在生命周期开始之前
``scope_of(root).provide(AppConfig, AppConfig(...))``，整张图拿到的就是替身，真单元
连构造都不会发生；替身照常跑自己的钩子、推进自己声明的依赖、被 ``stop()`` 回收。
"""

from __future__ import annotations

from canary_framework import Canary, scope_of


def unit[T: Canary](root: Canary, cls: type[T]) -> T:
    """The scope's instance of *cls* —— 0.9.x 里 ``canary[Type]`` 的替代写法。"""
    return scope_of(root).instances[cls]  # type: ignore[return-value]


def root_of(client) -> Canary:
    """The composition root behind a ``TestClient``."""
    return client.app.state.root  # type: ignore[no-any-return]


def payload(response):
    """Unwrap ``R`` and assert the call succeeded."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def failure(response) -> tuple[int, str]:
    """Unwrap ``R`` and assert the call reported a domain failure.

    失败同时出现在状态行和信封里，两者必须一致——这由 ``app/wiring.py`` 的那一个异常
    处理器保证。0.9.x 要靠每个 handler 自己记得 ``await ok(...)``，漏一个就变 500。
    """
    body = response.json()
    assert body["code"] != 0, body
    assert response.status_code == body["code"], response.text
    return body["code"], body["msg"]


def make_book(client, **overrides) -> dict:
    request = {
        "title": "分布式系统：概念与设计",
        "author": "George Coulouris",
        "category": "计算机",
        "copies": 1,
    }
    request.update(overrides)
    return payload(client.post("/api/catalog/books", json=request))


def make_reader(client, **overrides) -> dict:
    request = {"name": "张三", "level": "normal"}
    request.update(overrides)
    return payload(client.post("/api/readers/", json=request))


def make_overdue(client, loan_id: str, days: int) -> None:
    """Backdate a loan so that it is *days* days overdue, right now.

    写操作跑在 client 自己的事件循环门户上：异步引擎——以及内存 SQLite 被钉住的那一条
    连接——属于应用启动时所在的那个循环。
    """
    from datetime import timedelta

    from app.infra.db import Database
    from app.module.db.models import Loan, utcnow

    database = unit(root_of(client), Database)

    async def _age() -> None:
        async with database.begin() as session:
            loan = await session.get(Loan, loan_id)
            shift = loan.due_at - (utcnow() - timedelta(days=days))
            loan.due_at -= shift
            loan.borrowed_at -= shift
            session.add(loan)

    client.portal.call(_age)
