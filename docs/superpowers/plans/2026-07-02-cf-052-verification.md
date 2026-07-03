# cf 0.5.2 适配验证与 bug 报告 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Canary-Agent 建立 cf 0.5.2 行为回归测试套件，把已确认的框架/文档 bug 写入 doc/bug，并产出验证报告。

**Architecture:** pytest + Starlette TestClient，双层验证：真实 `AppModule`（装配层与真实端点）与玩具 cf service（本项目覆盖不到的框架行为，同时充当 bug 最小复现）。已实测确认两层注册表互不污染。

**Tech Stack:** Python 3.12、uv、pytest、starlette TestClient（httpx 已有）、canary-framework 0.5.2

## Global Constraints

- **不修改 `app/`、`main.py`、`config.py` 中任何代码**（规格边界：仅验证 + 报告）。
- 测试不依赖数据库与网络；不使用 TestClient 的 lifespan 上下文（避免触发 `startup()`）。
- bug 报告、功能期望、验证报告全部用**中文**。
- bug 报告命名 `doc/bug/NNN-<slug>.md`，功能期望 `doc/fet/NNN-<slug>.md`。
- 提交信息风格与仓库一致：简短中文描述，结尾带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 运行测试的唯一命令：`uv run pytest`（dev 依赖组自动安装）。
- 已实测的事实（计划中的期望值以此为准，不要"猜"）：
  - 缺失必填 query → 422；bool `YES`→True、`maybe`→422；`(body, 201)` 元组 → 201。
  - `dict` 请求体参数 + 无显式 `request_model` → 未绑定 → `TypeError`（TestClient 默认直接抛出）。
  - 路由冲突消息：`ValueError: Route collision: GET /ping`。
  - `AppModule` 装配后 `openapi()['paths']` 共 11 条，含 `/file/{kb_id}/{folder_path:path}`（转换器语法泄漏）。
  - `ModuleBase.init()` / `ServiceBase.init()` 为同步方法；`startup()`/`shutdown()` 为异步。
  - `canary_framework.engine` 下没有 `injector` 模块；`resolve_deps`/`topological_sort` 在 `canary_framework.engine.dependencies`，并从 `canary_framework.engine` 再导出。

---

### Task 1: pytest 脚手架与 dev 依赖

**Files:**
- Modify: `pyproject.toml`（追加 dev 依赖组与 pytest 配置）
- Create: `tests/__init__.py`（空文件）
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: fixture `app`（session 级，已 `init()` 的 `AppModule` 实例）、fixture `client`（`TestClient`，指向 `app.asgi_app`，`raise_server_exceptions=False`）。后续 Task 2/3 直接使用这两个 fixture 名。

- [ ] **Step 1: 在 pyproject.toml 追加 dev 依赖与 pytest 配置**

在 `pyproject.toml` 末尾（`[build-system]` 之后）追加：

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 创建空的 tests/__init__.py**

```bash
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 3: 写 tests/conftest.py**

```python
"""共享 fixture：装配真实 AppModule。

注意：TestClient 不使用 with 上下文（不触发 lifespan/startup），
测试因此不依赖数据库与网络。
"""

import pytest
from starlette.testclient import TestClient

from main import AppModule


@pytest.fixture(scope="session")
def app():
    instance = AppModule()
    instance.init()
    return instance


@pytest.fixture(scope="session")
def client(app):
    # raise_server_exceptions=False：handler 内未处理异常表现为 500 响应而非测试崩溃
    return TestClient(app.asgi_app, raise_server_exceptions=False)
```

- [ ] **Step 4: 验证收集空套件不报错**

Run: `uv run pytest --collect-only -q`
Expected: 退出码 5（no tests collected）或 0，无 import 错误。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py
git commit -m "添加 pytest 脚手架与 dev 依赖组"
```

---

### Task 2: 装配层验证（矩阵 #1、#3、#8、#9-OpenAPI、#10）

**Files:**
- Create: `tests/test_assembly.py`
- Test: `tests/test_assembly.py`

**Interfaces:**
- Consumes: fixture `app`、`client`（Task 1）。

- [ ] **Step 1: 写测试（含一个 xfail 标记已知 bug）**

```python
"""装配层：显式前缀、docs 端点、openapi() 记忆化、$ref 完整性。"""

import pytest

# 11 条业务路径（与各 Router 的显式 prefix 拼接结果）
EXPECTED_PATHS = {
    "/coll/create",
    "/coll/list",
    "/coll/{coll_id}/delete",
    "/file/{kb_id}/{folder_path:path}",
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


@pytest.mark.xfail(
    strict=True,
    reason="doc/bug/001：OpenAPI 路径泄漏 Starlette 转换器语法 {folder_path:path}",
)
def test_openapi_paths_are_valid_openapi_templates(app):
    """矩阵 #9（OpenAPI 部分）：OpenAPI path template 不允许 :converter 后缀。"""
    for p in app.openapi()["paths"]:
        assert ":" not in p, f"路径含转换器语法: {p}"
```

- [ ] **Step 2: 运行**

Run: `uv run pytest tests/test_assembly.py -v`
Expected: 6 项 PASS（parametrize 3 项算 3 个）+ 1 项 XFAIL，无 FAIL。

- [ ] **Step 3: Commit**

```bash
git add tests/test_assembly.py
git commit -m "添加 cf 0.5.2 装配层验证测试"
```

---

### Task 3: 真实端点请求管线验证（矩阵 #4、#9-路由、query 绑定）

**Files:**
- Create: `tests/test_request_pipeline.py`
- Test: `tests/test_request_pipeline.py`

**Interfaces:**
- Consumes: fixture `client`（Task 1）。

**背景（写进测试注释）：** 端点的 service 层把内部异常捕获为 `R.fail`（HTTP 200、`code != 0`）。测试无数据库运行，因此「HTTP 200 且返回 R 结构」即证明：路由匹配成功、参数绑定成功、handler 正常执行。绑定失败会表现为 400/404/422/500，与 200 可区分。

- [ ] **Step 1: 写测试**

```python
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


def test_path_converter_route_matching(client):
    """矩阵 #9（路由部分）：{folder_path:path} 匹配多级路径并与 query 共存。"""
    resp = client.get("/file/kb_x/a/b/c?page=1&size=10")
    assert resp.status_code == 200
    assert _is_r_payload(resp.json())


def test_path_converter_delete(client):
    """{folder_path:path} 在 DELETE 方法下同样匹配。"""
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
```

- [ ] **Step 2: 运行**

Run: `uv run pytest tests/test_request_pipeline.py -v`
Expected: 全部 PASS。若 `test_invalid_body_returns_422` 失败，先用
`uv run python -c "from app.module.kb.schema import CreateKbRequest; print(CreateKbRequest.model_fields)"`
确认 `name` 是否必填；若 schema 全部字段可选，把该测试的 json 改为类型错误值（如 `{"name": 123}`……pydantic 会 coerce，改用 `{"name": None}`）并保持断言 422。

- [ ] **Step 3: Commit**

```bash
git add tests/test_request_pipeline.py
git commit -m "添加真实端点请求管线验证测试"
```

---

### Task 4: 框架级玩具复现（矩阵 #2、#5、#6、#7 + bug 002 复现 + keyword 语义）

**Files:**
- Create: `tests/test_cf_behavior.py`
- Test: `tests/test_cf_behavior.py`

**Interfaces:**
- Consumes: 无（与 conftest 的 app fixture 无关，自建玩具 service）。
- Produces: 本文件同时是 doc/bug/002 的最小复现依据。

- [ ] **Step 1: 写测试**

```python
"""框架级行为验证：与本项目解耦的玩具 service。

已实测确认：@service() 注册表以 module 树为作用域，
本文件定义的玩具类不会污染 conftest 中的 AppModule 装配。
"""

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from canary_framework import module, service
from canary_framework.core.module import ModuleBase
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase


class Item(BaseModel):
    a: int


@service()
class Toy(ServiceBase):
    router = Router(prefix="/toy")

    @router.get("/req?q={q}")
    async def required_query(self, q: str):
        return {"q": q}

    @router.get("/flag?on={on}")
    async def bool_query(self, on: bool = False):
        return {"on": on}

    @router.post("/items")
    async def create_model(self, item: Item):
        return {"a": item.a}, 201

    @router.post("/dicts")
    async def create_dict(self, item: dict):
        return item, 201

    @router.get("/silent?page={page}")
    async def silent(self, page: int = 1, keyword: str | None = None):
        # keyword 未在路径字符串声明 —— 按文档语义永远保持默认值
        return {"page": page, "keyword": keyword}


@pytest.fixture(scope="module")
def toy_client():
    app = Toy()
    app.init()
    return TestClient(app.asgi_app, raise_server_exceptions=False)


def test_missing_required_query_is_422(toy_client):
    """矩阵 #5：缺失必填 query → 422（0.5.2 之前是 500）。"""
    assert toy_client.get("/toy/req").status_code == 422


def test_present_required_query_binds(toy_client):
    resp = toy_client.get("/toy/req?q=hi")
    assert resp.status_code == 200
    assert resp.json() == {"q": "hi"}


@pytest.mark.parametrize(
    "raw,expected",
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("false", False), ("No", False), ("off", False)],
)
def test_bool_query_parsing(toy_client, raw, expected):
    """矩阵 #6：bool query 大小写无关解析。"""
    resp = toy_client.get(f"/toy/flag?on={raw}")
    assert resp.status_code == 200
    assert resp.json() == {"on": expected}


def test_bool_query_invalid_is_422(toy_client):
    """矩阵 #6：无法识别的 bool 值 → 422（0.5.2 之前只认字面量 true）。"""
    assert toy_client.get("/toy/flag?on=maybe").status_code == 422


def test_tuple_return_sets_status_code(toy_client):
    """矩阵 #7：(body, status_code) 元组正确设置状态码（0.5.2 之前恒 200）。"""
    resp = toy_client.post("/toy/items", json={"a": 1})
    assert resp.status_code == 201
    assert resp.json() == {"a": 1}


@pytest.mark.xfail(
    strict=True,
    reason="doc/bug/002：dict 请求体参数（无显式 request_model）未绑定 → TypeError 500",
)
def test_dict_body_param_binds(toy_client):
    """web.md 的示例写法 `item: dict` —— 按文档应正常绑定。"""
    resp = toy_client.post("/toy/dicts", json={"a": 1})
    assert resp.status_code == 201


def test_undeclared_query_param_keeps_default(toy_client):
    """文档语义确认：带默认值但未在路径字符串声明的参数永不从查询串绑定。

    （对应应用层遗留问题：kb/router.py list_public 的 keyword 参数。）
    """
    resp = toy_client.get("/toy/silent?page=3&keyword=hello")
    assert resp.status_code == 200
    assert resp.json() == {"page": 3, "keyword": None}


def test_route_collision_raises_value_error():
    """矩阵 #2：相同 (method, full_path) 在组装时抛 ValueError。"""

    @service()
    class CollideA(ServiceBase):
        router = Router()

        @router.get("/ping")
        async def ping(self):
            return "a"

    @service()
    class CollideB(ServiceBase):
        router = Router()

        @router.get("/ping")
        async def ping(self):
            return "b"

    @module(services=[CollideA, CollideB])
    class CollideApp(ModuleBase):
        pass

    app = CollideApp()
    app.init()
    with pytest.raises(ValueError, match="Route collision: GET /ping"):
        _ = app.asgi_app
```

- [ ] **Step 2: 运行本文件**

Run: `uv run pytest tests/test_cf_behavior.py -v`
Expected: 13 项 PASS + 1 项 XFAIL（`test_dict_body_param_binds`），无 FAIL。

- [ ] **Step 3: 运行全套确认无注册表交叉污染**

Run: `uv run pytest -v`
Expected: 全部文件一起跑结果不变（Task 2/3 的测试仍 PASS）。

- [ ] **Step 4: Commit**

```bash
git add tests/test_cf_behavior.py
git commit -m "添加框架级行为玩具复现测试"
```

---

### Task 5: 文档审计（doc/zh 全部 11 篇 vs 已安装源码）

**Files:**
- Create: `/tmp/claude-1000/-home-canary-Projects-Canary-Agent/12aa0b82-c102-4ded-932a-bd417a3c7eb5/scratchpad/doc_audit.py`（一次性脚本，不入库）
- 产出：审计发现清单（保存到 scratchpad `audit_findings.md`，供 Task 6/8 引用）

- [ ] **Step 1: 写并运行 import 审计脚本**

```python
"""扫描 doc/zh/*.md 代码块中的 canary_framework import，逐条 exec 验证。"""

import re
from pathlib import Path

DOCS = Path("doc/zh")
pattern = re.compile(r"^(?:from|import)\s+canary_framework\S*.*$", re.M)

failures = []
for md in sorted(DOCS.glob("*.md")):
    for block in re.findall(r"```python\n(.*?)```", md.read_text(), re.S):
        for line in pattern.findall(block):
            try:
                exec(line, {})
            except Exception as e:
                failures.append((md.name, line, repr(e)))

for name, line, err in failures:
    print(f"{name}: {line}  ->  {err}")
print(f"\n共 {len(failures)} 条 import 失败")
```

Run: `uv run python <scratchpad>/doc_audit.py`
Expected: 至少报出 `dependency-injection.md` 的 `from canary_framework.engine.injector import ...`；记录所有输出。

- [ ] **Step 2: 人工核对每篇文档的 API 断言**

逐篇打开 `doc/zh/*.md`，对照 `.venv/lib/python3.12/site-packages/canary_framework/` 源码核对下列点，每发现一处差异记入 scratchpad `audit_findings.md`（格式：`文档文件:行号 | 文档说法 | 实际行为 | 证据`）：

1. `index.md` / `quickstart.md`：示例中 `init()` 的调用方式（同步 or `await`）；快速开始示例能否原样运行。
2. `core.md`：提到的内部函数/属性名（`_cf_collect_routes`、`_cf_assemble`、`Assembled`、`ResolvedRoute`）在源码中是否存在（用 `grep -rn <名字> .venv/lib/python3.12/site-packages/canary_framework/`）。
3. `services.md` / `modules.md`：`@service()`/`@module()` 的参数签名与文档一致（对照 `canary_framework/decorators`）。
4. `lifecycle.md`：`await app.init()` 示例（已立案）；`LifecycleHookError` 的 import 路径 `canary_framework.common` 是否成立。
5. `configuration.md`：`CanaryConfig` 字段表与 `canary_framework/common/config.py` 逐字段核对（名称、默认值）；`await app.init()`（已立案）。
6. `dependency-injection.md`：`engine.injector`（已立案）；`Registry`/`ServiceEntry` 的字段与源码核对。
7. `web.md`：`request_model` 自动探测的措辞（"第一个非路径/查询参数"）vs 实际只探测 BaseModel 子类（bug 002 的文档面）；OpenAPI 参数表与 `core/router/_base.py` 的装饰器签名核对。
8. `api-reference.md`：逐条 import 路径与签名核对（Step 1 脚本已覆盖 import；补人工核对签名）。
9. `whats-new.md`：五项修复与实测结果对照（Task 3/4 已验证，标注"已验证"）。

- [ ] **Step 3: 汇总**

把 Step 1/2 全部发现写入 scratchpad `audit_findings.md`，按「框架 bug / 文档 bug / 无问题」分类。

（本 Task 无仓库变更，不提交。）

---

### Task 6: 编写 doc/bug 报告

**Files:**
- Create: `doc/bug/001-openapi-path-converter-leak.md`
- Create: `doc/bug/002-dict-body-param-unbound.md`
- Create: `doc/bug/003-docs-await-init-mismatch.md`
- Create: `doc/bug/004-docs-engine-injector-path.md`
- Create: Task 5 新发现的差异，每条一个 `doc/bug/NNN-<slug>.md`（编号顺延）

**Interfaces:**
- Consumes: `tests/test_assembly.py`（bug 001 的 xfail）、`tests/test_cf_behavior.py`（bug 002 的 xfail）、scratchpad `audit_findings.md`。

- [ ] **Step 1: 写 001（模板同时定义了后续报告的结构，逐节保留）**

```markdown
# 001：OpenAPI 路径泄漏 Starlette 转换器语法 `{param:path}`

- **类型**：框架 bug
- **影响版本**：canary-framework 0.5.2
- **发现方式**：Canary-Agent 适配验证（tests/test_assembly.py::test_openapi_paths_are_valid_openapi_templates，xfail 在案）

## 最小复现

​```python
from canary_framework import service
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase

@service()
class Files(ServiceBase):
    router = Router(prefix="/file")

    @router.get("/{kb_id}/{folder_path:path}")
    async def get(self, kb_id: str, folder_path: str):
        return {"kb_id": kb_id, "folder_path": folder_path}

app = Files()
app.init()
print(list(app.openapi()["paths"]))
# 实际输出: ['/file/{kb_id}/{folder_path:path}']
​```

## 期望 vs 实际

- **期望**：OpenAPI 3.0.3 的 path template 只允许 `{name}`，转换器后缀应在生成文档时剥离，
  输出 `/file/{kb_id}/{folder_path}`（Starlette 路由表保留 `:path` 不受影响）。
- **实际**：`:path` 原样出现在 OpenAPI paths key 中，Swagger UI / 代码生成器会把它当作
  字面参数名处理，产出非法客户端代码。

## 疑似原因

路由收集时 full_path 直接由 `prefix + route_path` 拼接（`core/router/` 下的组装逻辑），
OpenAPI 生成（`engine/openapi.py`）复用了同一字符串，没有对 `{name:converter}` 做归一化。

## 备注

路由匹配本身正常（`tests/test_request_pipeline.py::test_path_converter_route_matching` 通过），
仅文档生成受影响。
```

- [ ] **Step 2: 写 002**

```markdown
# 002：`dict` 类型请求体参数（无显式 `request_model`）不绑定，抛出未处理的 TypeError

- **类型**：框架 bug（伴随文档矛盾）
- **影响版本**：canary-framework 0.5.2
- **发现方式**：Canary-Agent 适配验证（tests/test_cf_behavior.py::test_dict_body_param_binds，xfail 在案）

## 最小复现

​```python
from canary_framework import service
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase
from starlette.testclient import TestClient

@service()
class Items(ServiceBase):
    router = Router(prefix="/items")

    @router.post("/")
    async def create(self, item: dict):   # web.md 示例同款写法
        return item, 201

app = Items()
app.init()
client = TestClient(app.asgi_app)
client.post("/items/", json={"a": 1})
# TypeError: Items.create() missing 1 required positional argument: 'item'
#   （core/router/_utils.py:248 的 endpoint 调用 handler(**kwargs) 时 kwargs 缺 item）
​```

## 期望 vs 实际

- **期望**（按 `doc/zh/web.md`「请求体」一节：“处理器的请求体参数是第一个既非路径参数、也非查询参数的参数”，
  且同页「HTTP 方法装饰器」示例直接使用 `item: dict`）：JSON 请求体解析后以参数名传入，返回 201。
- **实际**：request_model 自动探测只认 BaseModel 子类参数；`dict` 参数既不绑定也不报可读错误，
  handler 调用直接 TypeError，客户端收到 500（且异常逃出 ASGI 应用，TestClient 默认配置下直接抛栈）。

## 疑似原因

自动探测逻辑只在参数注解是 `BaseModel` 子类时才认定请求体参数；`dict` 注解被跳过后，
调用 `handler(**kwargs)` 时缺参。加 `request_model=SomeModel` 或改用 BaseModel 注解即可绕过
（已实测两者均正常）。

## 修复方向（二选一）

1. 框架侧：非路径/查询的 `dict` 注解参数接收原始 JSON dict（与文档一致）；
2. 文档侧：web.md 删除 `item: dict` 示例并明确“请求体参数必须是 BaseModel 子类或配合显式 request_model”。
   即使选 2，缺参也应转成 4xx/500 的结构化错误响应，而不是未处理 TypeError。
```

- [ ] **Step 3: 写 003 / 004（同 001 的节结构：类型/影响版本/发现方式/复现或证据/期望 vs 实际/疑似原因）**

003 核心内容：`doc/zh/lifecycle.md`（「模块生命周期」`await app.init()`、「ASGI 生命周期」`await app.init()`、「配置」节示例）与 `doc/zh/configuration.md`（「将 Config 作为服务使用」`await app.init()`）示例均为异步调用；实测
`inspect.iscoroutinefunction(ModuleBase.init) == False`（`ServiceBase.init` 同为同步；`startup`/`shutdown` 是异步）。`await` 一个非 awaitable 返回值会直接 `TypeError`。类型：文档 bug。另注：lifecycle.md 的服务级示例 `async def init(self)` 与基类同步签名不一致，需要框架作者澄清子类是否允许 async 覆写（若允许，谁来 await 它）。

004 核心内容：`doc/zh/dependency-injection.md`「手动注入」节 `from canary_framework.engine.injector import topological_sort, resolve_deps` —— 实际不存在 `injector` 模块（`ModuleNotFoundError` 实测），真实位置 `canary_framework.engine.dependencies`，且两个函数从 `canary_framework.engine` 再导出。类型：文档 bug。

- [ ] **Step 4: Task 5 的新发现各写一份报告（编号 005 起）**

每条按 001 的节结构写；纯文档差异归「文档 bug」，行为差异先在 python 里最小复现确认再归「框架 bug」，复现不出来的**不写**（记入验证报告的“未能确认”即可）。

- [ ] **Step 5: Commit**

```bash
git add doc/bug/
git commit -m "记录 cf 0.5.2 验证发现的框架与文档 bug"
```

---

### Task 7: doc/fet 功能期望（仅写验证中自然产生的）

**Files:**
- Create: `doc/fet/001-structured-error-responses.md`（下述 Step 1 内容）
- Create: 审计中自然产生的其他期望（有则写，无则跳过）

- [ ] **Step 1: 写 001**

内容要点（中文，节结构：动机 / 期望行为 / 与设计理念的契合）：

- **动机**：验证中观察到 handler 内未处理异常（bug 002 的 TypeError）会逃出 ASGI 应用；
  TestClient 需要 `raise_server_exceptions=False` 才能拿到 500。商业 API 需要稳定的
  JSON 错误契约（如 `{"code": 500, "msg": "..."}`），而不是裸 traceback/连接中断。
- **期望行为**：框架提供全局异常 → 结构化 JSON 响应的兜底层，且允许应用注册自定义
  exception handler（类似 Starlette 的 `exception_handlers`，但走 cf 的装饰器风格）。
- **契合**：与 0.5.2「路径冲突是真正的报错」同一哲学——错误显式、可观测；
  与强类型校验理念互补（请求侧已有 422 契约，响应侧缺同等契约）。

- [ ] **Step 2: Commit**

```bash
git add doc/fet/
git commit -m "记录对 canary-framework 的功能期望"
```

---

### Task 8: 验证报告与全套收尾

**Files:**
- Create: `doc/verification-0.5.2.md`
- Test: 全套 `uv run pytest`

- [ ] **Step 1: 跑全套并记录输出**

Run: `uv run pytest -v 2>&1 | tail -30`
Expected: 0 failed；2 xfailed（bug 001、002）；其余全部 passed。把统计行原样贴进报告。

- [ ] **Step 2: 写 doc/verification-0.5.2.md**

结构（中文）：

1. **结论一句话**：Canary-Agent 与 cf 0.5.2 兼容良好，迁移在先前提交中已完成；本轮验证 10/10 项矩阵全部有测试覆盖，发现框架 bug 2 个、文档 bug ≥2 个（见 doc/bug）。
2. **验证矩阵结果表**：规格里的 10 行矩阵 + 「结果」列（通过 / xfail→bug 编号）+ 「测试位置」列（文件::测试名）。
3. **bug 与 fet 索引**：doc/bug、doc/fet 各文件一行摘要。
4. **应用层遗留问题（超出本轮范围，未修改）**：
   - `app/module/kb/router.py` `list_public` 的 `keyword` 未在路径字符串声明，永不绑定（语义已由 `tests/test_cf_behavior.py::test_undeclared_query_param_keeps_default` 证实）；修复：路径改为 `'/public/list?page={page}&size={size}&keyword={keyword}'`。
   - `app/module/kb/router.py` `'/{kb_id}/dalete'` 拼写错误（对外 API 路径，修复属破坏性变更，需要用户决定）。
   - `pyproject.toml` 声明 langgraph 但代码零引用；建议下一轮移除并按规划引入 pydantic-ai。
   - `app/shared/coze/service.py` 空壳类名 `KbService` 与 `app/module/kb/service.py::KbService` 重名，未注册进任何 module。
   - `app/module/db/repository/*` 用同步 `create_engine` 配 `postgresql+asyncpg` URL——sync/async 驱动不匹配，连接时会失败，建议下一轮统一（本轮无 DB 未触发）。
5. **运行方式**：`uv run pytest`；xfail 语义说明（框架修复后 strict xfail 会变 FAIL 提醒移除标记）。

- [ ] **Step 3: 核对报告与实际产出一致**

逐项检查：矩阵行数=10、bug 索引与 doc/bug 文件一一对应、测试名与实际文件中的函数名逐字一致（grep 核对）。

- [ ] **Step 4: Commit**

```bash
git add doc/verification-0.5.2.md
git commit -m "产出 cf 0.5.2 适配验证报告"
```

---

## Self-Review 记录

- **规格覆盖**：矩阵 10 项 → Task 2（#1/#3/#8/#9-OpenAPI/#10）、Task 3（#4/#9-路由 + query 绑定）、Task 4（#2/#5/#6/#7）；文档审计 → Task 5；doc/bug → Task 6；doc/fet → Task 7；验证报告 → Task 8；「不改应用代码」→ 全局约束。无缺口。
- **占位符扫描**：Task 6 Step 3/4 与 Task 7 为内容要点式（产出为散文文档，要点即规格）；测试代码全部完整给出。
- **类型/命名一致性**：fixture 名 `app`/`client`/`toy_client`、xfail reason 中的 bug 编号、报告引用的测试名已互相核对。
