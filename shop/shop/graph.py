"""The graph the existing application mounts.

被已有应用挂上来的那张图。它是一个普通的根单元：依赖两个路由单元，再加上老代码要够到的
那几个单元。

它**不认识 HTTP**：没有 ``asgi.Server``，也没有 ``asgi.fastapi.App``。应用和监听都沿用
现有的（``shop/asgi.py``、uvicorn），这张图只提供路由单元与业务单元——这正是 ``mount()``
存在的理由。
"""

from __future__ import annotations

from canary_framework import Canary, dep

from shop.catalog import Catalog
from shop.inventory import InventoryApi
from shop.pricing import PricingApi, PricingRules
from shop.settings import PaymentSettings, ShopSettings


class ShopGraph(Canary):
    """The root: two router units, and the units the legacy routes reach for.

    根单元。
    """

    config = dep(ShopSettings)
    payment = dep(PaymentSettings)
    catalog = dep(Catalog)
    pricing = dep(PricingApi)
    inventory = dep(InventoryApi)
    rules = dep(PricingRules)
