"""Test helpers shipped with the package.

They live here rather than in ``tests/conftest.py`` so that both scenarios in
this workspace can keep a directory called ``tests/`` without their helper
modules colliding on import.
"""

from __future__ import annotations


def effective_config(canary):
    """The ``AppConfig`` instance the runtime actually built and shared.

    配置回到普通 ``@cocoa`` 节点之后，它就在图上，``canary[AppConfig]`` 直接取得到
    ——0.9.3 里"注解声明的配置不是节点、运行时给不出访问入口"那个洞随之消失。
    """
    from config import AppConfig

    return canary[AppConfig]


def payload(response):
    """Unwrap ``R`` and assert the call succeeded."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def failure(response) -> tuple[int, str]:
    """Unwrap ``R`` and assert the call reported a domain failure.

    失败同时出现在状态行和信封里：``app.common.errors.ok()`` 把 ``DomainError.code``
    落到 ``JSONResponse`` 的状态码上。两者必须一致——不一致说明某个 handler 漏掉了
    ``await ok(...)``，领域异常正在裸奔。
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

    The write runs on the client's own event loop portal, because the async
    engine — and the single connection an in-memory SQLite is pinned to — belong
    to the loop the application was started on.
    """
    from datetime import timedelta

    from app.infra.db import Database
    from app.module.db.models import Loan, utcnow

    database = client.canary[Database]

    async def _age() -> None:
        async with database.begin() as session:
            loan = await session.get(Loan, loan_id)
            shift = loan.due_at - (utcnow() - timedelta(days=days))
            loan.due_at -= shift
            loan.borrowed_at -= shift
            session.add(loan)

    client.portal.call(_age)
