"""迁移：老接口一行没改，新模块挂在 ``/v2``，两边共用同一批单元。

这个场景的全部主张就是这句话，所以这个文件逐条验证它。
"""

from __future__ import annotations

import pytest
from canary_framework.test import running, unit

from shop.catalog import Catalog
from shop.graph import ShopGraph
from shop.pricing import PricingRules
from shop.warehouse import MainWarehouse, OverflowWarehouse


async def test_the_old_routes_still_work(client) -> None:
    """``/v1`` 是老代码：模块级 ``APIRouter`` + ``Depends``，一行没动。"""
    health = await client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["api"] == "v1"
    assert (await client.get("/v1/orders")).json() == []


async def test_the_new_modules_are_mounted_under_v2(client) -> None:
    """``mount(root, APIRouter(prefix="/v2"))`` —— 路由单元的前缀叠在这个前缀之下。"""
    listing = await client.get("/v2/inventory")
    assert listing.status_code == 200
    assert [item["sku"] for item in listing.json()] == ["QC-1001", "QC-1002", "QC-2001"]

    quote = await client.get("/v2/pricing/QC-1001", params={"level": "vip"})
    assert quote.status_code == 200
    body = quote.json()
    assert body["discount_cents"] == 1280
    assert body["total_cents"] == 12284
    assert body["provider"] == "alipay"


async def test_a_half_migrated_route_reaches_a_unit(client) -> None:
    """老路由 + 新单元：桥是 ``bridge.use(Catalog)``，三行，形状由老代码决定。"""
    created = await client.post("/v1/orders", params={"sku": "QC-1001", "quantity": 2})
    assert created.status_code == 201
    assert created.json()["cents"] == 25600

    missing = await client.post("/v1/orders", params={"sku": "QC-9999", "quantity": 1})
    assert missing.status_code == 404

    too_many = await client.post("/v1/orders", params={"sku": "QC-1002", "quantity": 999})
    assert too_many.status_code == 409


async def test_both_generations_share_the_same_units(client) -> None:
    """``/v2`` 改掉的库存，``/v1`` 立刻看得见——背后是同一个 ``Catalog`` 实例。"""
    await client.post("/v2/inventory/QC-2001/move", json={"quantity": 25})
    moved = (await client.get("/v2/inventory")).json()
    assert [item for item in moved if item["sku"] == "QC-2001"][0]["stock"] == {
        "main": 25,
        "overflow": 0,
    }
    # 老路由下的订单也按新库存判断
    assert (await client.post("/v1/orders", params={"sku": "QC-2001", "quantity": 20})).status_code == 201


async def test_moving_more_than_there_is_fails(client) -> None:
    refused = await client.post("/v2/inventory/QC-1002/move", json={"quantity": 5})
    assert refused.status_code == 400
    assert "只有 0 件" in refused.json()["detail"]


async def test_one_openapi_document_covers_both_generations(client) -> None:
    """一个应用，一份文档——这是"沿用现有应用"的好处之一。"""
    paths = set((await client.get("/openapi.json")).json()["paths"])
    assert {"/v1/health", "/v1/orders"} <= paths
    assert {"/v2/inventory", "/v2/inventory/{sku}/move", "/v2/pricing/{sku}"} <= paths
    assert (await client.get("/docs")).status_code == 200


async def test_the_two_warehouses_are_two_units_with_two_configs(client) -> None:
    """同一份配置的两个实例 = 两个子类，各读自己的 ``env_prefix``。"""
    warehouses = (await client.get("/v2/inventory/warehouses")).json()
    assert warehouses == [
        {"code": "main", "city": "上海", "cutoff_hour": 18},
        {"code": "overflow", "city": "嘉兴", "cutoff_hour": 12},
    ]


async def test_the_bridge_refuses_outside_the_lifespan(app) -> None:
    """图没启动时，老路由取单元直接报错——不是拿到一个半死的对象。"""
    import httpx

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="图还没启动"):
            await client.post("/v1/orders", params={"sku": "QC-1001", "quantity": 1})


# -- 不要 FastAPI ---------------------------------------------------------


async def test_the_graph_runs_without_any_web_layer() -> None:
    """这张图不认识 HTTP：没有 ``Server``，没有 ``App``，路由单元也是普通单元。

    所以最便宜的那层测试在这里：``running(ShopGraph)`` 之后直接 await 接口方法。
    """
    async with running(ShopGraph) as root:
        assert root.config.store_name == "青瓷商城"

        quote = await root.pricing.quote("QC-1001", level="vip")
        assert quote.total_cents == 12284

        stock = await root.inventory.list()
        assert len(stock) == 3

        # 够到一个自己没声明依赖的单元
        assert unit(root, Catalog) is root.catalog
        assert unit(root, PricingRules) is root.pricing.rules
        assert unit(root, MainWarehouse).code == "main"
        assert unit(root, OverflowWarehouse).code == "overflow"


async def test_the_catalogue_is_only_loaded_while_the_graph_runs() -> None:
    """``@start`` 装载、``@stop`` 卸掉——迁移场景里这一点很关键，见边界测试。"""
    async with running(ShopGraph) as root:
        assert root.catalog.loaded is True
    assert root.catalog.loaded is False
