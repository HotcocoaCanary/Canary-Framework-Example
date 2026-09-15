"""Test helpers shipped with the package.

放在包里而不是 ``tests/conftest.py``，是为了两个场景都能有一个叫 ``tests/`` 的目录而
不在 import 时撞车。

其中 :func:`seed` 是 0.10.0 的替换缝。框架没有 ``provide=`` 之类的替换入口，但
``Scope.instances`` 本来就是"类型 → 本次运行的唯一实例"那张表，而 ``dep(...)`` 读的
正是它——所以在生命周期开始之前把替身放进去，整张图拿到的就是替身，真单元连构造都
不会发生。
"""

from __future__ import annotations

from canary_framework import Canary, Scope, scope_of


def seed[T: Canary](scope: Scope, cls: type[Canary], instance: T) -> T:
    """Register *instance* as *scope*'s instance of *cls*, before the lifecycle starts.

    ``adopt`` 把作用域写到替身身上（替身自己声明的依赖因此也解析得了），再按 *cls*
    这个键登记一次——``adopt`` 用的键是 ``type(instance)``，而依赖声明的是 *cls*。
    """
    scope.adopt(instance)
    scope.instances[cls] = instance
    return instance


def unit[T: Canary](root: Canary, cls: type[T]) -> T:
    """The scope's instance of *cls* —— 0.10.0 里 ``canary[Type]`` 的替代写法。"""
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
