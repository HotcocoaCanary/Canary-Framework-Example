"""The old application —— untouched, except for one endpoint that was half-migrated.

老代码，一行都没改——除了最后那一个接口：它已经开始用迁过来的 ``Catalog`` 了。

这个文件的写法和框架没有任何关系：模块级的 ``APIRouter``、模块级的状态、
``Depends(get_now)``、一个 ``FastAPI`` 对象。**这正是重点**：迁移的第一步不用动它一行，
只是换成由我们的 ``Server`` 来服务（``shop/server.py`` 的阶段一）——服务器只认 ASGI 协议。
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Annotated, Any

from canary_framework import Canary
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from shop.bridge import attach, use
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


def create_legacy(root: Canary) -> FastAPI:
    """The existing application, exactly as it was —— 加的只是"挂上图"这一句。

    老应用自己带着它的异常处理器与 ``/`` 首页。``attach(app, root)`` 是那座桥要的：老路由
    用 ``Depends`` 从 ``app.state.graph`` 上按类型取单元。
    """
    app = FastAPI(title="青瓷商城后台", version="2.0.0")
    app.include_router(router)

    @app.get("/", tags=["老接口"])
    async def index() -> dict[str, str]:
        return {"v1": "老接口", "/v2": "迁过来的模块（阶段二才有）", "docs": "/docs"}

    async def bad_request(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    app.add_exception_handler(ValueError, bad_request)
    attach(app, root)
    return app
