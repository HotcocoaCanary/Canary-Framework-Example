"""Real endpoints: route matching and parameter binding under Canary 0.9.

无数据库运行：service 层捕获内部异常返回 R.fail（HTTP 200, code != 0），
因此 200 + R 结构 == 路由匹配、参数绑定、handler 调用全部成功。
"""


def _is_r_payload(body: dict) -> bool:
    return {"code", "data", "msg"} <= set(body.keys())


def test_query_binding_get_kb_list(client):
    """GET /kb/list?page=2&size=5 binds declared query parameters."""
    resp = client.get("/kb/list?page=2&size=5")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_query_defaults_get_kb_list(client):
    """Omitted query parameters fall back to their defaults."""
    resp = client.get("/kb/list")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_path_param_plus_body_patch(client):
    """PATCH /kb/{kb_id}/update binds a path parameter and a body together."""
    resp = client.patch("/kb/kb_x/update", json={"name": "新名字"})
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_list_with_folder_query(client):
    """/file 列表：folder_path 作为查询参数（含多级路径 a/b/c），与 page/size 共存。

    ``folder_path`` remains a query parameter so values may contain ``/``.
    """
    resp = client.get("/file/kb_x?folder_path=a/b/c&page=1&size=10")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_list_root_default(client):
    """Omitted folder_path means the root directory."""
    resp = client.get("/file/kb_x")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_delete_with_folder_query(client):
    """DELETE /file binds the required folder_path query parameter."""
    resp = client.delete("/file/kb_x?folder_path=a/b/c")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_delete_missing_folder_is_422(client):
    """DELETE without required folder_path returns 422."""
    resp = client.delete("/file/kb_x")
    assert resp.status_code == 422


def test_post_with_body_only(client):
    """POST /kb/create parses and validates the body model."""
    resp = client.post("/kb/create", json={"name": "测试库"})
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_invalid_body_returns_422(client):
    """An invalid body returns 422 (CreateKbRequest.name is required)."""
    resp = client.post("/kb/create", json={})
    assert resp.status_code == 422
