"""Inventory —— the router unit that reads both warehouses.

库存。两个仓库是两个单元，所以"调拨"这件事写起来就是两个依赖之间的事，不需要一张
"仓库名 → 实例"的表。

前缀里带着 ``/v2``：这个应用单元被 ``dispatch`` 挂在 ``/v2`` 下，而 ``dispatch`` 只转发、
不改写路径，所以路由自己要包含它（见 ``shop/graph.py`` 的 ``V2Api.path``）。
"""

from __future__ import annotations

from canary_framework import dep
from canary_framework.web.asgi.app import Router, get, post
from pydantic import BaseModel

from shop.catalog import Catalog
from shop.warehouse import MainWarehouse, OverflowWarehouse


class Move(BaseModel):
    """A stock transfer between the two warehouses."""

    quantity: int = 1
    to_overflow: bool = False


class StockView(BaseModel):
    sku: str
    title: str
    list_cents: int
    stock: dict[str, int]
    on_hand: int


class InventoryApi(Router, prefix="/v2/inventory"):
    """``/inventory`` 与 ``/inventory/{sku}/move``"""

    catalog = dep(Catalog)
    main = dep(MainWarehouse)
    overflow = dep(OverflowWarehouse)

    @get("")
    async def list(self) -> list[StockView]:
        return [StockView(**product.view()) for product in self.catalog.all()]

    @get("/warehouses")
    async def warehouses(self) -> list[dict[str, object]]:
        return [self.main.view(), self.overflow.view()]

    @post("/{sku}/move")
    async def move(self, sku: str, body: Move) -> StockView:
        product = self.catalog.require(sku)
        source, target = (self.main, self.overflow) if body.to_overflow else (self.overflow, self.main)
        available = product.stock.get(source.code, 0)
        if available < body.quantity:
            raise ValueError(f"{source.code} 只有 {available} 件")
        product.stock[source.code] = available - body.quantity
        product.stock[target.code] = product.stock.get(target.code, 0) + body.quantity
        return StockView(**product.view())
