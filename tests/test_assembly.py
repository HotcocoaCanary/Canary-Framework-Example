"""装配层：显式前缀、docs 端点、openapi() 记忆化、$ref 完整性。"""

import pytest

# 11 条业务路径（与各 Router 的显式 prefix 拼接结果）
EXPECTED_PATHS = {
    "/coll/create",
    "/coll/list",
    "/coll/{coll_id}/delete",
    "/file/{kb_id}",
    "/kb/create",
    "/kb/list",
    "/kb/public/list",
    "/kb/{kb_id}/dalete",
    "/kb/{kb_id}/join",
    "/kb/{kb_id}/shared",
    "/kb/{kb_id}/update",
}


def test_explicit_prefix_paths(app):
    """矩阵 #1：无 /{ServiceName} 自动命名空间，路径 = prefix + route path。"""
    paths = set(app.openapi()["paths"].keys())
    assert paths == EXPECTED_PATHS


def test_no_service_name_namespace(app):
    """矩阵 #1：旧的 /KBRouter、/FileRouter 等隐式挂载不复存在。"""
    for p in app.openapi()["paths"]:
        assert "Router" not in p


def test_openapi_public_and_memoized(app):
    """矩阵 #3：openapi() 是公开方法且记忆化（两次调用同一对象）。"""
    first = app.openapi()
    second = app.openapi()
    assert first is second


def test_openapi_refs_resolvable(app):
    """矩阵 #8：所有 $ref 都能在 components/schemas 中解析（无悬空引用）。"""
    import json

    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    raw = json.dumps(spec)
    refs = {
        seg.split("/")[-1].rstrip('"')
        for seg in raw.split('"$ref": "')[1:]
        for seg in [seg.split('"')[0]]
    }
    missing = {r for r in refs if r not in schemas}
    assert not missing, f"悬空 $ref: {missing}"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_endpoints(client, path):
    """矩阵 #10：docs 三端点可访问。"""
    assert client.get(path).status_code == 200


def test_openapi_paths_are_valid_openapi_templates(app):
    """OpenAPI path template 不允许 :converter 后缀。

    应用已改用查询参数（不再使用 {folder_path:path}），所有路径均为合法 template。
    """
    for p in app.openapi()["paths"]:
        assert ":" not in p, f"路径含转换器语法: {p}"
