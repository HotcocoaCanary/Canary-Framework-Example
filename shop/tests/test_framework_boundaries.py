"""框架边界：``mount()`` 这一侧的行为与坑。

和另外几个场景的同名文件一样：不测业务，只记录**框架当前的行为**。标 **【毛病】** 的
是这个场景试出来的问题。

路径一律从 ``app.openapi()["paths"]` 读，不去翻 ``app.routes``——FastAPI 0.143 把
``include_router`` 的结果包成了内部对象（``_IncludedRouter``），翻内部结构的测试会在
FastAPI 升级时假红。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework import Canary, dep
from canary_framework.asgi.fastapi import Router, get, mount
from canary_framework.test import running
from fastapi import APIRouter, FastAPI

from shop.asgi import create_app
from shop.graph import ShopGraph


def paths_of(app: FastAPI) -> set[str]:
    """The application's paths, read through the public API."""
    app.openapi_schema = None  # 强制重算，免得读到上一次的缓存
    return set(app.openapi()["paths"])


# -- mount 的基本行为 ------------------------------------------------------


async def test_mounting_into_an_application_puts_routers_at_their_own_prefix() -> None:
    """``mount(root, app)``：应用是顶层，路由单元各在自己的前缀下。"""
    app = FastAPI()
    async with running(ShopGraph) as root:
        mount(root, app)
        assert {"/inventory", "/pricing/{sku}"} <= paths_of(app)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/inventory")).status_code == 200


async def test_mounting_into_a_router_keeps_the_router_prefix() -> None:
    """``mount(root, APIRouter(prefix="/v2"))``：前缀叠在外层之下——迁移时用这一种。"""
    app = FastAPI()
    api = APIRouter(prefix="/v2")
    async with running(ShopGraph) as root:
        mount(root, api)
        app.include_router(api)
        paths = paths_of(app)
        assert "/v2/inventory" in paths
        assert "/inventory" not in paths


async def test_a_router_unit_can_be_mounted_twice_on_purpose() -> None:
    """同一张图挂到两个前缀下：两套 URL，一个实例。

    迁移时有用——``/v2`` 与 ``/beta`` 指向同一批单元。代价见下面那条【毛病】：
    ``mount()`` 不记得自己挂过，所以"故意挂两次"和"不小心挂两次"长得一模一样。
    """
    app = FastAPI()
    async with running(ShopGraph) as root:
        for prefix in ("/v2", "/beta"):
            api = APIRouter(prefix=prefix)
            mount(root, api)
            app.include_router(api)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v2/inventory/QC-2001/move", json={"quantity": 5})
            beta = (await client.get("/beta/inventory")).json()
    moved = [item for item in beta if item["sku"] == "QC-2001"][0]
    assert moved["stock"] == {"main": 5, "overflow": 20}  # /v2 改的，/beta 看得见


async def test_only_routers_reached_directly_are_mounted() -> None:
    """路由单元只有被**直接**依赖时才会被挂载——隔着一个普通单元就不会。

    这是文档写明的规则，但症状很安静：接口不见了，不报错。
    """

    class Hidden(Router, prefix="/hidden"):
        @get("")
        async def hello(self) -> str:
            return "hi"

    class Middle(Canary):
        hidden = dep(Hidden)  # 普通单元依赖一个路由单元

    class Root(Canary):
        middle = dep(Middle)

    app = FastAPI()
    async with running(Root) as root:
        mount(root, app)
    assert not [path for path in paths_of(app) if "hidden" in path]


async def test_mounting_before_the_lifecycle_fails_with_a_bare_key_error() -> None:
    """**【毛病】** 在生命周期开始之前调 ``mount()``，抛的是裸 ``KeyError``。

    ``mount`` 从作用域的实例表里取依赖，而图是第一次进入生命周期时才建立的。所以
    "忘了在 lifespan 里挂"这个很常见的错误，得到的是 ``KeyError: <class ...>``，而不是
    像读 ``dep`` 那样的一句 ``LifecycleError: ... is unavailable before the lifecycle
    begins``。文档只说了"必须在依赖都已就位之后调用"。
    """
    app = FastAPI()
    with pytest.raises(KeyError):
        mount(ShopGraph(), app)


# -- 【毛病】mount 没有反操作，也不幂等 ------------------------------------


async def test_mount_is_not_idempotent_and_a_second_lifespan_breaks_the_app() -> None:
    """**【毛病】** 同一个应用对象进出 lifespan 两次，路由被挂两遍，而且**第一遍赢**。

    ``mount()`` 只往应用上加路由，没有反操作，也没有"已经挂过了"的检查。于是：

    1. 第一次 lifespan：图 A 启动，路由指向图 A 的单元；
    2. 退出：图 A 回收（``Catalog`` 卸载）；
    3. 第二次 lifespan：图 B 启动，又挂一遍，但先注册的那条路由仍然在前；
    4. 请求因此打在**已经停掉的图 A** 上 —— 503，而图 B 好好的。

    ``TestClient`` 复用同一个 ``app``、测试里对同一个应用进出两次、任何"重启图但不重建
    应用"的写法，都会掉进去。症状还很难查：FastAPI 只在重算 OpenAPI 时抱怨一句
    "Duplicate Operation ID"。

    期望的行为是 ``mount()`` 幂等（或重复挂载时报错），再加一个把路由摘下来的办法。
    """
    app = create_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/v2/inventory")).status_code == 200

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            stale = await client.get("/v2/inventory")
    assert stale.status_code == 503  # 打在第一张（已经停掉的）图上
    assert "目录未装载" in stale.json()["detail"]

    # 唯一的外部信号：重算 OpenAPI 时的重复 operation id
    app.openapi_schema = None
    with pytest.warns(UserWarning, match="Duplicate Operation ID"):
        app.openapi()


async def test_the_routes_outlive_the_graph() -> None:
    """同一件事的另一面：lifespan 退出之后路由还在，但背后的单元已经空了。

    所以新模块的单元最好像 ``Catalog`` 这样**直说**自己没在运行（这里是 503），而不是
    返回一个空列表让调用方以为库存清零了。
    """
    app = create_app()
    async with app.router.lifespan_context(app):
        pass

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        after = await client.get("/v2/inventory")
    assert after.status_code == 503


# -- 挂载发生在应用启动之后，OpenAPI 跟不跟得上 -----------------------------


async def test_the_openapi_schema_catches_up_with_a_late_mount() -> None:
    """挂载发生在 lifespan 里，也就是**应用启动之后**；OpenAPI 跟不跟得上取决于 FastAPI。

    FastAPI 0.143 记了一个路由版本号，路由变了就重算，所以启动前读过 schema 也不影响。
    但框架声明的下界是 ``fastapi>=0.121``，而 0.121 的 ``app.openapi()`` 是**无条件缓存**
    的（本机核对过）：在那个版本上，任何"启动前读一次 schema"的工具——CI 导出 OpenAPI、
    启动时打日志——会让 ``/openapi.json`` 永久停在没有新模块的那一份上。

    绕法是挂完之后 ``app.openapi_schema = None``。更该做的是 ``mount()`` 自己做这一步：
    它知道自己挂到了哪个应用上，而调用方不该为了一个 FastAPI 版本差异去记这件事。
    """
    app = create_app()
    before = app.openapi()
    assert "/v2/inventory" not in before["paths"]

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            schema = (await client.get("/openapi.json")).json()
    assert "/v2/inventory" in schema["paths"]
