"""How the legacy routes reach a unit.

老路由怎么拿到图上的单元。

``mount()`` 管的是**路由单元**：它把一张图上的路由挂到你的应用上。但迁移期还有一堆老
路由没改——它们是普通的 FastAPI 函数，用 ``Depends``，而它们也要用到已经迁过来的业务
单元。这中间需要一座桥，而桥不该是框架的事：它只有三行，而且形状由你的老代码决定。

这就是 ``library`` 在 0.10 时期的 ``wiring.py`` 做的事。那个文件在 ``library`` 里已经
不需要了（它整个换成了路由单元），但**迁移期**需要它——两种写法同时在一个应用里跑，
正是迁移的定义。

``use(Cls)`` 是一个 FastAPI 依赖::

    Catalogue = Annotated[Catalog, use(Catalog)]

    @router.get("/v1/stock/{sku}")
    async def stock(sku: str, catalogue: Catalogue) -> dict:
        return catalogue.require(sku).view()
"""

from __future__ import annotations

from typing import Any

from canary_framework import Canary
from canary_framework.test import unit as lookup
from fastapi import Depends

_root: Canary | None = None


def bind(root: Canary) -> None:
    """Remember the running graph —— 在 lifespan 里调用。"""
    global _root
    _root = root


def unbind() -> None:
    """Forget it again —— 图停了之后，老路由也该拿不到单元。"""
    global _root
    _root = None


def use(cls: type[Canary]) -> Any:
    """A FastAPI dependency that resolves *cls* from the running graph.

    从正在运行的那张图里按类型取单元。图没启动时直接报错，而不是返回一个半死的对象。

    ``canary_framework.test.unit`` 在这里不是"测试辅助"——它就是"按类型取回单元"，
    迁移期的桥正需要这一个动作。日常代码仍然应当声明依赖（``dep(...)``），所以这个函数
    只该出现在老路由里。
    """

    def resolve() -> Canary:
        if _root is None:
            raise RuntimeError("图还没启动：lifespan 之外没有单元可取")
        return lookup(_root, cls)

    return Depends(resolve)
