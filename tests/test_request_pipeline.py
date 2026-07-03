"""真实端点：0.5.2 请求管线下的路由匹配与参数绑定。

无数据库运行：service 层捕获内部异常返回 R.fail（HTTP 200, code != 0），
因此 200 + R 结构 == 路由匹配、参数绑定、handler 调用全部成功。
"""

import pytest


def _is_r_payload(body: dict) -> bool:
    return {"code", "data", "msg"} <= set(body.keys())


def test_query_binding_get_kb_list(client):
    """GET /kb/list?page=2&size=5 —— 路径字符串声明的 query 参数正常绑定。"""
    resp = client.get("/kb/list?page=2&size=5")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_query_defaults_get_kb_list(client):
    """省略 query 参数时保留默认值，不报错。"""
    resp = client.get("/kb/list")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_path_param_plus_body_patch(client):
    """矩阵 #4：PATCH /kb/{kb_id}/update 同时携带 path 参数与请求体，不再 500。"""
    resp = client.patch("/kb/kb_x/update", json={"name": "新名字"})
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


@pytest.mark.xfail(
    strict=True,
    reason="doc/bug/001：{param:path} 转换器参数不被 cf 识别，绑定缺参 → TypeError 500",
)
def test_path_converter_route_matching(client):
    """矩阵 #9（路由部分）：{folder_path:path} 匹配多级路径并与 query 共存。

    Starlette 层路由能匹配（非 404），但 cf 的 _PARAM_PATTERN 不识别
    转换器语法，folder_path 永不绑定，当前实际返回 500。
    """
    resp = client.get("/file/kb_x/a/b/c?page=1&size=10")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


@pytest.mark.xfail(
    strict=True,
    reason="doc/bug/001：{param:path} 转换器参数不被 cf 识别，绑定缺参 → TypeError 500",
)
def test_path_converter_delete(client):
    """{folder_path:path} 在 DELETE 方法下同样匹配（当前同样 500，见 doc/bug/001）。"""
    resp = client.delete("/file/kb_x/a/b/c")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_post_with_body_only(client):
    """POST /kb/create：显式 request_model 的请求体解析与校验。"""
    resp = client.post("/kb/create", json={"name": "测试库"})
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_invalid_body_returns_422(client):
    """请求体未通过 request_model 校验 → 422（CreateKbRequest.name 必填）。"""
    resp = client.post("/kb/create", json={})
    assert resp.status_code == 422
