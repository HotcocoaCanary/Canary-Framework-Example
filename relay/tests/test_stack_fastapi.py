"""只属于 FastAPI 那一层的东西：OpenAPI、``/docs``、``tags``，以及 ``path`` 带来的那个坑。

两层 HTTP 对外的路径、状态码、响应体是一致的（``test_parity.py`` 逐条比对过），所以这里
只放**换成 web 版就没有**的东西。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework.test import running

from relay.clock import Clock
from relay.http import fastapi as layer
from relay.settings import AdminSettings, EdgeSettings
from relay.testing import ManualClock

TOKEN = "test-token"


@pytest.fixture
async def relay_fastapi():
    """The whole process on the FastAPI layer, both ports on 0."""
    doubles = {
        EdgeSettings: EdgeSettings(host="127.0.0.1", port=0, site_id="test-site", sweep_interval_seconds=3600.0),
        AdminSettings: AdminSettings(host="127.0.0.1", port=0, token=TOKEN),
        Clock: ManualClock(),
    }
    async with running(layer.Relay, doubles) as root:
        yield root


@pytest.fixture
async def public(relay_fastapi):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{relay_fastapi.public.port}") as client:
        yield client


@pytest.fixture
async def admin(relay_fastapi):
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{relay_fastapi.admin.port}", headers={"x-admin-token": TOKEN}
    ) as client:
        yield client


async def test_openapi_covers_the_public_routers(public) -> None:
    schema = (await public.get("/openapi.json")).json()
    paths = set(schema["paths"])
    assert {"/devices", "/devices/{device_id}/heartbeat", "/health"} <= paths
    # 管理口的接口不在这份文档里：它是另一个应用单元，另一份 OpenAPI。
    assert not [path for path in paths if path.startswith("/admin")]
    assert schema["info"]["title"] == "门店边缘中继"


async def test_tags_group_the_endpoints(public) -> None:
    schema = (await public.get("/openapi.json")).json()
    tags = {tag for path in schema["paths"].values() for op in path.values() for tag in op.get("tags", [])}
    assert {"设备", "健康"} <= tags


async def test_the_second_application_has_its_own_docs_url(admin) -> None:
    """``path`` 不是 ``/`` 的应用，FastAPI 自带的那几个 URL 也必须挪进自己的前缀。

    ``docs_url`` 默认是 ``/docs``，但 ``/docs`` 不在 ``/admin`` 之下、不会被分发到这个
    应用——所以 ``AdminApp`` 显式写了 ``docs_url="/admin/docs"``。忘了写就是"接口好的，
    文档 404"。web 版没有这个坑，因为它根本没有 OpenAPI。
    """
    assert (await admin.get("/admin/docs")).status_code == 200
    assert (await admin.get("/admin/openapi.json")).status_code == 200
    assert (await admin.get("/docs")).status_code == 404


async def test_a_trailing_slash_redirects(public) -> None:
    """FastAPI 对尾斜杠做重定向：``/devices/`` → 307 到 ``/devices``。

    web 版不做重定向（尾斜杠严格区分），这是两层唯一的路由行为差异，
    ``test_stack_web.py`` 里有对应的一条。
    """
    answer = await public.get("/devices/")
    assert answer.status_code == 307
    assert answer.headers["location"].endswith("/devices")
