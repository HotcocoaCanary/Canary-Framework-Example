# 001：`{param:converter}` 路径参数端到端不支持（绑定失败 500 + OpenAPI 泄漏）

- **类型**：框架 bug
- **影响版本**：canary-framework 0.5.2
- **严重性**：高——使用 Starlette 转换器语法的路由完全不可用（本项目 `/file` 模块全部 4 个端点受影响）
- **发现方式**：Canary-Agent 适配验证
  - `tests/test_cf_behavior.py::test_path_converter_param_binds`（xfail 在案，最小复现）
  - `tests/test_request_pipeline.py::test_path_converter_route_matching` / `test_path_converter_delete`（真实端点，xfail 在案）
  - `tests/test_assembly.py::test_openapi_paths_are_valid_openapi_templates`（OpenAPI 面，xfail 在案）

## 最小复现

```python
from canary_framework import service
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase
from starlette.testclient import TestClient

@service()
class Toy(ServiceBase):
    router = Router(prefix="/t")

    @router.get("/conv/{p:path}")
    async def conv(self, p: str):
        return {"p": p}

app = Toy()
app.init()
client = TestClient(app.asgi_app)
client.get("/t/conv/a/b/c")
# TypeError: Toy.conv() missing 1 required positional argument: 'p'
#   （core/router/_utils.py:248 endpoint 调用 handler(**kwargs) 时 kwargs 缺 p）

print(list(app.openapi()["paths"]))
# ['/t/conv/{p:path}']   ← OpenAPI path template 非法保留 :path
print(app.openapi()["paths"]["/t/conv/{p:path}"]["get"].get("parameters", []))
# []                     ← 参数在 OpenAPI 中完全缺失
```

普通 `{p}` 写法一切正常，差异仅在转换器后缀。

## 期望 vs 实际

三个症状，同一根因：

| 面 | 期望 | 实际 |
|---|---|---|
| 请求绑定 | `p` 绑定为 `"a/b/c"`（Starlette 的 `request.path_params` 里就有） | `p` 永不进入 kwargs → handler TypeError → 500 |
| OpenAPI 路径 | `/t/conv/{p}`（生成文档时剥离转换器后缀；OpenAPI 3.0.3 template 只允许 `{name}`） | `/t/conv/{p:path}` 原样泄漏 |
| OpenAPI 参数 | `p` 出现在 parameters 列表 | 缺失（`[]`） |

## 根因（已定位）

`core/router/_utils.py:17`：

```python
_PARAM_PATTERN = r"\{(\w+)\}"
```

`\w+` 不含冒号，`{p:path}` 整体不被识别为路径参数：

1. 路由收集时 `path_params` 列表里没有 `p` → 请求时 `for name in info.path_params` 循环跳过它，kwargs 缺参；
2. OpenAPI 生成复用同一解析结果 → 参数缺失，且 full_path 字符串未做归一化 → `:path` 泄漏进 path key。

Starlette 自身的路由正则是 `\{([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?\}`（支持可选转换器），因此 Starlette 层路由匹配正常（非 404），错位发生在 cf 的绑定层。

## 修复建议

`_PARAM_PATTERN` 改为兼容转换器语法（如 `r"\{(\w+)(?::\w+)?\}"`），路径参数名取捕获组 1；
OpenAPI 生成时对 full_path 做 `{name:conv}` → `{name}` 归一化。若决定不支持转换器，
则应在路由注册时显式抛错，而不是留到运行时 500。

## 备注

未处理的 TypeError 会直接逃出 ASGI 应用（TestClient 默认配置下抛栈而非返回 500 响应），
相关体验问题另见 doc/fet/001。
