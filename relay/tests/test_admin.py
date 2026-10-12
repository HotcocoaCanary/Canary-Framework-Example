"""管理端口：第二个应用、共享的单元、挪过的文档地址。

这个文件压的是"一个进程多个端口"这件事的四个后果。
"""

from __future__ import annotations

import httpx
import pytest
from canary_framework.test import unit

from relay.metrics import Metrics


async def test_the_two_ports_are_different_servers(relay) -> None:
    assert relay.public.port != relay.admin.port
    assert relay.public.host == relay.admin.host == "127.0.0.1"
    # 两个 Server 都不是根单元，根单元自己不监听任何东西。
    assert not hasattr(relay, "port")


async def test_admin_needs_the_token(relay) -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{relay.admin.port}") as naked:
        assert (await naked.get("/admin/fleet")).status_code == 403
        assert (await naked.get("/admin/fleet", headers={"x-admin-token": "wrong"})).status_code == 403


async def test_admin_sees_what_the_public_port_wrote(public, admin) -> None:
    """两个端口，一份状态——``Fleet`` 在图上只有一个实例。"""
    await public.post("/devices/pos-1/heartbeat", json={"kind": "pos"})
    await public.post("/devices/pos-1/events", json={"kind": "paper_out"})

    overview = (await admin.get("/admin/fleet")).json()
    assert overview["site"] == "test-site"
    assert overview["summary"] == {"online": 1}
    assert [d["device_id"] for d in overview["devices"]] == ["pos-1"]

    events = (await admin.get("/admin/fleet/pos-1/events")).json()
    assert [event["kind"] for event in events] == ["paper_out"]


async def test_quarantine_shows_up_on_the_public_port(public, admin) -> None:
    await public.post("/devices/pos-1/heartbeat", json={})
    assert (await admin.post("/admin/fleet/pos-1/quarantine")).json()["status"] == "quarantined"
    assert (await public.get("/devices/pos-1")).json()["status"] == "quarantined"
    assert (await admin.post("/admin/fleet/pos-1/quarantine?on=false")).json()["status"] == "online"


async def test_one_metrics_unit_on_two_ports(public, admin, relay) -> None:
    """``Metrics`` 被两个 ``Server`` 依赖，但图上只有一个实例。"""
    assert unit(relay, Metrics) is relay.public.metrics
    assert relay.public.metrics is relay.admin.metrics

    await public.post("/devices/pos-1/heartbeat", json={})
    on_public = (await public.get("/metrics")).text
    on_admin = (await admin.get("/metrics")).text
    assert 'relay_heartbeats_total{site="test-site"} 1' in on_public
    assert on_public == on_admin


@pytest.mark.parametrize(
    ("path", "status"),
    [("/admin", 404), ("/admin/health", 200), ("/admin/fleet", 200), ("/admin/zzz", 404)],
)
async def test_the_admin_app_only_sees_its_own_prefix(admin, path: str, status: int) -> None:
    """``dispatch`` 只转发不改写：应用看到的仍是完整路径，所以路由自己带着 ``/admin``。

    ``/admin`` 本身没有接口——前缀不是路由。
    """
    assert (await admin.get(path)).status_code == status
