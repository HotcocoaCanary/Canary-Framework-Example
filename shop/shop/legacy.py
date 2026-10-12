"""The old code —— untouched, except for one endpoint that was half-migrated.

老代码，一行都没改——除了最后那一个接口：它已经开始用迁过来的 ``Catalog`` 了。

这个文件的写法和框架没有任何关系：模块级的 ``APIRouter``、模块级的状态、
``Depends(get_now)``。迁移的意义就在于这些东西**不必**先全部改掉：``mount()`` 把新模块
挂在同一个应用上，两种写法在一个进程里共存，直到老的那边被逐个搬完。
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from shop.bridge import use
from shop.catalog import Catalog

router = APIRouter(prefix="/v1", tags=["老接口"])

#: 老系统的"数据库"：一个模块级的 dict。迁移的第一步从来不是动它。
_ORDERS: dict[str, dict[str, Any]] = {}
_IDS = itertools.count(1)


def get_now() -> datetime:
    """The old way of getting the time —— 一个模块级函数加 ``Depends``。"""
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(get_now)]
#: 已经迁过来的单元，经由 ``bridge.use`` 取回。
Catalogue = Annotated[Catalog, use(Catalog)]


@router.get("/health")
async def health(now: Now) -> dict[str, str]:
    return {"status": "ok", "now": now.isoformat(), "api": "v1"}


@router.get("/orders")
async def orders() -> list[dict[str, Any]]:
    return list(_ORDERS.values())


@router.post("/orders", status_code=201)
async def create_order(sku: str, quantity: int, now: Now, catalogue: Catalogue) -> dict[str, Any]:
    """The half-migrated one: old route, new unit.

    半迁完的那个：路由还是老的，库存已经读新的单元了。
    """
    try:
        product = catalogue.require(sku)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"没有这个商品: {sku}") from None
    if sum(product.stock.values()) < quantity:
        raise HTTPException(status_code=409, detail="库存不足")
    order_id = f"v1-{next(_IDS):04d}"
    _ORDERS[order_id] = {
        "order_id": order_id,
        "sku": sku,
        "title": product.title,
        "quantity": quantity,
        "cents": product.list_cents * quantity,
        "created_at": now.isoformat(),
    }
    return _ORDERS[order_id]
