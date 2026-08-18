# 001：单个 handler 的类型注解无法生成 schema 会让整份 OpenAPI 文档 500

- **类型**：框架 bug
- **影响版本**：canary-framework 0.9.1（0.9.0 起即存在，非本次修复引入）
- **严重性**：中——不影响业务请求本身，但会让 `/openapi.json`、进而 `/docs`（Swagger UI）
  整份文档失效；触发面是「任意一个 handler 的参数或返回值类型注解 Pydantic 无法生成
  schema」，属于容易在日常开发中无意踩到的坑（拼错类型、忘记用 Pydantic 模型、引用了
  第三方非 Pydantic 类）。
- **发现方式**：Canary-Agent 同步验证 0.9.1 时的探索性测试（非既有测试用例覆盖）

## 最小复现

```python
import asyncio
from canary_framework import Canary
from canary_framework.web import get, web_cocoa
from starlette.testclient import TestClient

class Weird:          # 任意非 Pydantic、无 __get_pydantic_core_schema__ 的类型
    pass

@web_cocoa
class T:
    @get('/x')
    async def x(self, w: Weird):
        return 'ok'

with TestClient(Canary(T)) as client:
    client.get('/openapi.json')
```

```
pydantic.errors.PydanticSchemaGenerationError: Unable to generate pydantic-core
schema for <class '__main__.Weird'>. Set `arbitrary_types_allowed=True` ...
  File ".../canary_framework/web/core/openapi.py", line 135, in _schema
    adapter = TypeAdapter(annotation)
  File ".../canary_framework/web/core/openapi.py", line 95, in _operation
    schema = _schema(type_, schemas)
  File ".../canary_framework/web/core/openapi.py", line 68, in build_openapi
    paths.setdefault(path, {})[method.lower()] = _operation(fn, path, schemas)
  File ".../canary_framework/web/core/app.py", line 35, in openapi_endpoint
    return JSONResponse(build_openapi(title, version, routes))
```

`GET /openapi.json` 返回 500（未捕获异常直接逃出 ASGI 应用）。同一进程里其余所有路由
（包括与 `Weird` 毫无关系的路由）的 OpenAPI 文档也一并不可用，因为 `build_openapi` 是
单次遍历全部 routes、遇错即抛，没有按路由隔离。

顺带验证：应用**启动**（`app.init()` / `app.start()`）阶段不校验这一点——`Canary(T)`
能正常 `init()`/`start()`，问题只在真正访问 `/openapi.json` 时才暴露；对该路由发起
业务请求（`GET /x`）也不会经过 `_schema()`，只会因为 `Weird` 被当成 query 参数而返回
`422 missing query parameter: w`，即请求路径和文档路径对同一处错误标注给出两种互不相关
的失败信息，都没有指出「这是 handler `T.x` 的参数 `w: Weird` 无法处理」。

## 期望 vs 实际

| 面 | 期望 | 实际 |
|---|---|---|
| 装配/启动期 | 遇到无法生成 schema 的类型时报错，指出类名、方法名、参数名（对应反馈文档 P0 #4 的诉求） | 不校验，`init()`/`start()` 均成功 |
| `/openapi.json` | 要么该路由的 schema 退化为 `{}`（视为不透明类型）并附警告，要么给出定位到具体 handler 的 4xx/500 错误 | Pydantic 内部异常原样冒泡为 500，堆栈里看不到是哪个 `@cocoa` 类的哪个方法 |
| 影响范围 | 单个坏路由不应波及其它路由的文档 | 一个 handler 的类型问题让整份 OpenAPI 文档（因而 `/docs`、`/redoc`）对所有路由都不可用 |

## 根因（已定位）

`src/canary_framework/web/core/openapi.py`：

- `_schema()`（约第 132-138 行）直接 `TypeAdapter(annotation)` 后 `.json_schema()`，
  没有 `try/except` 兜底。
- `_operation()` 对每个参数、以及返回值类型都调用 `_schema()`。
- `build_openapi()` 用一个 `for` 循环遍历全部 routes 依次调用 `_operation()`，
  没有 per-route 隔离（比如 `try/except` 后把该路由标记为「文档生成失败」而不是让
  整个函数抛出）。
- `src/canary_framework/web/core/app.py` 的 `openapi_endpoint` 直接
  `JSONResponse(build_openapi(...))`，同样没有兜底，异常直接穿透到 ASGI 层。

## 修复建议

1. `_schema()` 捕获 `PydanticSchemaGenerationError`（以及更通用的 `PydanticUndefinedAnnotation`
   等），失败时至少返回 `{}` 或 `{"type": "object", "description": "<未知类型：Weird>"}`
   之类的占位 schema，不让单个类型污染整份文档。
2. 更彻底的做法是把校验提前到装配期（`Canary.start()`/`web_cocoa` 收集路由时）：对每个
   handler 的参数和返回值跑一遍 `_schema()` 或等价探测，失败就在启动时抛出
   `RouteRegistrationError`，消息里带上类名、方法名、参数名（呼应反馈文档 P0 #4 的建议，
   与已经做到的「重复路由启动期报错」保持同一严重性级别）。
3. 顺带一提：目前 `duplicate route: {method} {path}`（`web/core/app.py:59`）的报错信息里
   只有 method 和 path，没有类名/方法名，也未完全达到反馈文档 P0 #3「错误信息要包含类名、
   方法名、完整路径」的要求，建议一并补上。

## 备注

不影响本次 0.9.1 验证的结论——Canary-Agent 当前所有 handler 的参数/返回值都是
Pydantic 模型或标量，不会触发这条路径，纯属为框架团队后续加固记录。
