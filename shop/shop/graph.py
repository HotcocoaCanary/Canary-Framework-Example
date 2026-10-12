"""The graph: the business units, and the application unit the new modules live in.

这张图分两部分：

* ``ShopGraph`` —— 业务那一半（商品目录、算钱规则、三份配置）。老应用要用的就是它。
* ``V2Api`` —— 迁过来的新模块，一个**应用单元**，``path = "/v2"``。它自己就是一个 ASGI
  应用，所以既能和老应用并排站在同一个端口上（见 ``shop/server.py``），也能单独交给
  uvicorn。

迁移的两个阶段就是"图上有没有 ``V2Api``"：

* 阶段一：只有 ``ShopGraph``——老应用一行不改，只是换成由我们的 ``Server`` 来服务；
* 阶段二：加上 ``V2Api``——新模块作为另一个 ASGI 应用，按路径与老应用并存。
"""

from __future__ import annotations

from canary_framework import Canary, dep
from canary_framework.web.asgi.app import App, Request, Response, error

from shop.catalog import Catalog, CatalogNotLoaded
from shop.inventory import InventoryApi
from shop.pricing import PricingApi, PricingRules
from shop.settings import PaymentSettings, ShopSettings

#: 迁过来的模块落在这个前缀下，和老的 ``/v1`` 并排。
NEW_API_PREFIX = "/v2"


class ShopGraph(Canary):
    """The business half —— 老应用与新模块共用的那张图。

    它不认识 HTTP：没有服务器，也没有应用。
    """

    config = dep(ShopSettings)
    payment = dep(PaymentSettings)
    catalog = dep(Catalog)
    rules = dep(PricingRules)


class V2Api(App):
    """The migrated modules —— an application unit that answers under ``/v2``.

    ``path`` 是给服务器看的：它决定这个应用在哪个前缀下被调用。``dispatch`` 不改写路径，
    所以下面两个路由单元的前缀自己带着 ``/v2``（``InventoryApi`` 写的是
    ``/v2/inventory``）。
    """

    inventory = dep(InventoryApi)
    pricing = dep(PricingApi)

    path = NEW_API_PREFIX

    @error(CatalogNotLoaded)
    async def not_loaded(self, _: Request, exc: CatalogNotLoaded) -> Response:
        """目录没装载（图没在跑）：说清楚，而不是返回一个空列表。"""
        return Response.json({"detail": str(exc)}, status=503)

    @error(KeyError)
    async def missing(self, _: Request, exc: KeyError) -> Response:
        return Response.json({"detail": f"没有这个商品: {exc.args[0]}"}, status=404)

    @error(ValueError)
    async def refused(self, _: Request, exc: ValueError) -> Response:
        return Response.json({"detail": str(exc)}, status=400)
