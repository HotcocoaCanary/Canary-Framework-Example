"""真实端点：0.5.2 请求管线下的路由匹配与参数绑定。

无数据库运行：service 层捕获内部异常返回 R.fail（HTTP 200, code != 0），
因此 200 + R 结构 == 路由匹配、参数绑定、handler 调用全部成功。
"""


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


def test_file_list_with_folder_query(client):
    """/file 列表：folder_path 作为查询参数（含多级路径 a/b/c），与 page/size 共存。

    cf 不解析 Starlette 转换器语法，故 folder_path 由路径参数改为查询参数
    （查询值允许含斜杠）。这是「应用侧规避」而非依赖框架修复。
    """
    resp = client.get("/file/kb_x?folder_path=a/b/c&page=1&size=10")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_list_root_default(client):
    """folder_path 省略 → 根目录（可选查询参数），不报错。"""
    resp = client.get("/file/kb_x")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_delete_with_folder_query(client):
    """DELETE /file：folder_path 查询参数（必填），含多级路径。"""
    resp = client.delete("/file/kb_x?folder_path=a/b/c")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_file_delete_missing_folder_is_422(client):
    """DELETE 缺失必填 folder_path → 422。"""
    resp = client.delete("/file/kb_x")
    assert resp.status_code == 422


def test_post_with_body_only(client):
    """POST /kb/create：显式 request_model 的请求体解析与校验。"""
    resp = client.post("/kb/create", json={"name": "测试库"})
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_invalid_body_returns_422(client):
    """请求体未通过 request_model 校验 → 422（CreateKbRequest.name 必填）。"""
    resp = client.post("/kb/create", json={})
    assert resp.status_code == 422
