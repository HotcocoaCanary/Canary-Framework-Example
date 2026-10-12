"""迁移：老接口一行没改，新模块作为另一个 ASGI 应用并存。

两个阶段：

* 阶段一 —— 只换服务器。老应用（原生 FastAPI）由我们的 ``Server`` 服务，图由 Canary 启动。
* 阶段二 —— 新模块（一个应用单元，``path = "/v2"``）与老应用按路径分发，共用同一张图。

老接口的断言在两个阶段都跑：迁移的第一条要求就是"老的不许变样"。
"""

from __future__ import annotations

import pytest
from canary_framework.test import running, unit

from shop.catalog import Catalog
from shop.graph import ShopGraph, V2Api
from shop.pricing import PricingRules
from shop.server import Stage1, Stage2
from shop.warehouse import MainWarehouse, OverflowWarehouse

# --- 老接口：两个阶段都不许变样 ---------------------------------------------


async def test_the_old_routes_work_in_both_stages(client) -> None:
    """``/v1`` 是老代码：模块级 ``APIRouter`` + ``Depends`` + 模块级状态，一行没动。"""
    health = await client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["api"] == "v1"
    assert (await client.get("/v1/orders")).json() == []
    assert (await client.get("/")).json()["v1"] == "老接口"


async def test_a_half_migrated_route_reaches_a_unit(client) -> None:
    """老路由 + 新单元：桥是 ``bridge.use(Catalog)``，三行，形状由老代码决定。"""
    created = await client.post("/v1/orders", params={"sku": "QC-1001", "quantity": 2})
    assert created.status_code == 201
    assert created.json()["cents"] == 25600

    assert (await client.post("/v1/orders", params={"sku": "QC-9999", "quantity": 1})).status_code == 404
    assert (await client.post("/v1/orders", params={"sku": "QC-1002", "quantity": 999})).status_code == 409


async def test_the_old_application_keeps_its_own_openapi(client) -> None:
    """老应用的 ``/docs`` 与 OpenAPI 原样还在——换服务器不碰它。"""
    assert (await client.get("/docs")).status_code == 200
    paths = set((await client.get("/openapi.json")).json()["paths"])
    assert {"/v1/health", "/v1/orders", "/"} <= paths
    # 新模块不在这份文档里：它是另一个应用，而且那一层不生成 OpenAPI
    assert not [path for path in paths if path.startswith("/v2")]


# --- 阶段一：只换服务器 -----------------------------------------------------


async def test_stage_one_serves_the_old_application_and_nothing_else() -> None:
    """阶段一什么都没搬：``/v2`` 还不存在。

    但已经拿到了想要的东西——进程的生命周期归 Canary：``ShopGraph`` 上的单元按依赖顺序
    启动与回收，老应用不必再自己写 lifespan。
    """
    server = type("T", (Stage1,), {"host": "127.0.0.1", "port": 0})
    async with running(server) as listening:
        import httpx

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listening.port}") as client:
            assert (await client.get("/v1/health")).status_code == 200
            assert (await client.get("/v2/inventory")).status_code == 404
        assert unit(listening, Catalog).loaded is True, "图是由 Server 启动的"


async def test_the_server_serves_a_foreign_application() -> None:
    """``Server`` 服务的是 ASGI 应用，不问出处：这里给它的是一个 FastAPI 对象。

    这就是"先只换服务器"能成立的原因，也是框架不再包装 FastAPI 的理由——协议两侧各自
    守协议即可。
    """
    from fastapi import FastAPI

    server = type("T", (Stage1,), {"host": "127.0.0.1", "port": 0})()
    await server.init()
    assert isinstance(server.app, FastAPI)
    await server.stop()


# --- 阶段二：两个应用按路径并存 ---------------------------------------------


async def test_stage_two_puts_the_new_modules_beside_the_old_application() -> None:
    server = type("T", (Stage2,), {"host": "127.0.0.1", "port": 0})
    async with running(server) as listening:
        import httpx

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listening.port}") as client:
            assert (await client.get("/v1/health")).status_code == 200

            listed = await client.get("/v2/inventory")
            assert listed.status_code == 200
            assert [item["sku"] for item in listed.json()] == ["QC-1001", "QC-1002", "QC-2001"]

            quote = (await client.get("/v2/pricing/QC-1001", params={"level": "vip"})).json()
            assert (quote["discount_cents"], quote["total_cents"]) == (1280, 12284)


async def test_both_generations_share_the_same_units() -> None:
    """``/v2`` 改掉的库存，``/v1`` 立刻看得见——背后是同一个 ``Catalog`` 实例。"""
    server = type("T", (Stage2,), {"host": "127.0.0.1", "port": 0})
    async with running(server) as listening:
        import httpx

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listening.port}") as client:
            await client.post("/v2/inventory/QC-2001/move", json={"quantity": 25})
            moved = [row for row in (await client.get("/v2/inventory")).json() if row["sku"] == "QC-2001"]
            assert moved[0]["stock"] == {"main": 25, "overflow": 0}
            # 老路由按新库存判断
            assert (await client.post("/v1/orders", params={"sku": "QC-2001", "quantity": 20})).status_code == 201


async def test_moving_more_than_there_is_fails(v2_client) -> None:
    refused = await v2_client.post("/v2/inventory/QC-1002/move", json={"quantity": 5})
    assert refused.status_code == 400
    assert "只有 0 件" in refused.json()["detail"]


async def test_the_two_warehouses_are_two_units_with_two_configs(v2_client) -> None:
    """同一份配置的两个实例 = 两个子类，各读自己的 ``env_prefix``。"""
    warehouses = (await v2_client.get("/v2/inventory/warehouses")).json()
    assert warehouses == [
        {"code": "main", "city": "上海", "cutoff_hour": 18},
        {"code": "overflow", "city": "嘉兴", "cutoff_hour": 12},
    ]


# --- 不要 HTTP ---------------------------------------------------------------


async def test_the_business_half_runs_without_any_web_layer(graph) -> None:
    """``ShopGraph`` 不认识 HTTP：没有服务器，没有应用。"""
    assert graph.config.store_name == "青瓷商城"
    assert graph.rules.quote("QC-1001", level="vip").total_cents == 12284
    assert unit(graph, Catalog) is graph.catalog
    assert unit(graph, PricingRules) is graph.rules


async def test_the_migrated_modules_are_units_too() -> None:
    """新模块那一层：路由是单元，接口方法不经 HTTP 也能调。"""
    async with running(V2Api) as api:
        stock = await api.inventory.list()
        assert len(stock) == 3
        assert unit(api, MainWarehouse).code == "main"
        assert unit(api, OverflowWarehouse).code == "overflow"
        assert api.inventory.catalog is unit(api, Catalog)


async def test_the_catalogue_is_only_loaded_while_the_graph_runs() -> None:
    """``@start`` 装载、``@stop`` 卸掉——所以"图没在跑"这件事接口能直说（503）。"""
    async with running(ShopGraph) as root:
        assert root.catalog.loaded is True
    assert root.catalog.loaded is False


async def test_the_bridge_refuses_outside_a_graph() -> None:
    """桥没挂上图时直说——而不是在某个接口里冒出 ``AttributeError``。"""
    from shop.bridge import graph as read_graph

    class Bare:
        class app:  # noqa: N801 - 模仿 request.app
            class state:  # noqa: N801
                pass

    with pytest.raises(RuntimeError, match="还没有挂上图"):
        await read_graph(Bare())  # type: ignore[arg-type]
