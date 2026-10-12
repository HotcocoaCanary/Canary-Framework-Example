"""对外端口：接入、查询、分发。

这个文件有两组测试，针对同一批接口：一组走**真实套接字**（``public``），一组只打应用单元
（``api_client``）。两者的结果必须一致——不一致的地方就是"服务器与分发"这一层带来的，
比如 ``/metrics`` 与 ``/ws/events`` 只有前者有。
"""

from __future__ import annotations

import pytest
from canary_framework.test import running

from relay.clock import Clock
from relay.schema import Heartbeat
from relay.settings import EdgeSettings


async def test_heartbeat_registers_a_device(public) -> None:
    response = await public.post(
        "/devices/pos-1/heartbeat", json={"kind": "pos", "metrics": {"paper": 0.8}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == "pos-1"
    assert body["status"] == "online"
    assert body["heartbeats"] == 1
    assert body["metrics"] == {"paper": 0.8}


async def test_heartbeat_is_idempotent_and_counts(public, relay) -> None:
    for _ in range(3):
        await public.post("/devices/scale-7/heartbeat", json={"kind": "scale"})
    listed = (await public.get("/devices")).json()
    assert [d["device_id"] for d in listed] == ["scale-7"]
    assert listed[0]["heartbeats"] == 3
    assert relay.counters.value("relay_heartbeats_total") == 3
    assert relay.counters.value("relay_devices_seen_total") == 1


async def test_events_need_a_known_device(public) -> None:
    missing = await public.post("/devices/ghost/events", json={"kind": "tamper"})
    assert missing.status_code == 404
    assert missing.json()["device_id"] == "ghost"

    await public.post("/devices/pos-1/heartbeat", json={})
    accepted = await public.post("/devices/pos-1/events", json={"kind": "paper_out"})
    assert accepted.status_code == 202
    assert accepted.json() == {"accepted": True, "type": "paper_out", "device_id": "pos-1"}


async def test_health_reports_the_site_and_the_fleet(public) -> None:
    await public.post("/devices/pos-1/heartbeat", json={})
    body = (await public.get("/health")).json()
    assert body["status"] == "ok"
    assert body["site"] == "test-site"
    assert body["devices"] == {"online": 1}


async def test_metrics_is_served_on_the_same_port(public) -> None:
    """``/metrics`` 不是 FastAPI，但和 FastAPI 应用在同一个端口上。"""
    await public.post("/devices/pos-1/heartbeat", json={})
    response = await public.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'relay_up{site="test-site"} 1' in body
    assert 'relay_heartbeats_total{site="test-site"} 1' in body
    assert 'relay_devices{site="test-site",status="online"} 1' in body


@pytest.mark.parametrize("path", ["/", "/nope", "/metricsx", "/devicesx"])
async def test_unmatched_paths_are_404(public, path: str) -> None:
    """``/`` 交给 FastAPI 应用（它自己 404）；``/metricsx`` 不属于 ``/metrics``。

    前缀按整段匹配，所以 ``/metricsx`` 落到 ``/`` 上，而不是落到 ``/metrics`` 上。
    """
    assert (await public.get(path)).status_code == 404


# -- 同一批接口，不要服务器 ------------------------------------------------


async def test_the_application_alone_answers_the_same(api_client) -> None:
    """没有 ``Server``、没有端口、没有分发：只启动 ``PublicApi`` 这一个应用单元。"""
    created = await api_client.post("/devices/pos-9/heartbeat", json={"kind": "pos"})
    assert created.status_code == 200
    assert (await api_client.get("/health")).json()["site"] == "test-site"
    assert [d["device_id"] for d in (await api_client.get("/devices")).json()] == ["pos-9"]


async def test_without_a_server_there_is_no_dispatch(api_client) -> None:
    """``/metrics`` 与 ``/ws/events`` 是**别的应用单元**，不在这个应用里。

    ASGITransport 直接打 ``PublicApi.app``，所以这里只有 FastAPI 的路由；分发是
    ``Server`` 那一层的事。两种测法的差别就在这一条。
    """
    assert (await api_client.get("/metrics")).status_code == 404


async def test_endpoint_methods_are_plain_bound_methods(layer, clock) -> None:
    """路由单元仍是普通类：接口方法可以不经 HTTP 直接 await。

    ``get`` / ``post`` 只打标记、不改造方法，所以这是最便宜的一层测试——没有 HTTP、
    没有 JSON、没有服务器，只有对象。
    """
    doubles = {EdgeSettings: EdgeSettings(site_id="bare"), Clock: clock}
    async with running(layer.PublicApi, doubles) as api:
        view = await api.devices.heartbeat("pos-1", Heartbeat(kind="pos", metrics={"paper": 0.5}))
        assert (view.device_id, view.status, view.heartbeats) == ("pos-1", "online", 1)

        health = await api.health.health()
        assert health["site"] == "bare"
        assert health["devices"] == {"online": 1}

        # 共享的两个单元就是同一个实例
        assert api.devices.fleet is api.health.fleet
