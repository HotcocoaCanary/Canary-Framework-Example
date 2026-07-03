# 002：`dict` 类型请求体参数（无显式 `request_model`）不绑定，抛出未处理的 TypeError

- **类型**：框架 bug（伴随文档矛盾）
- **影响版本**：canary-framework 0.5.2
- **发现方式**：Canary-Agent 适配验证（`tests/test_cf_behavior.py::test_dict_body_param_binds`，xfail 在案）

## 最小复现

```python
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
```

## 期望 vs 实际

- **期望**（按 `doc/zh/web.md`「请求体」一节：“处理器的请求体参数是第一个既非路径参数、也非查询参数的参数”，
  且同页「HTTP 方法装饰器」与「返回值」的示例直接使用 `item: dict`）：JSON 请求体解析后以参数名传入，返回 201。
- **实际**：request_model 自动探测只认 `BaseModel` 子类参数；`dict` 参数既不绑定也不报可读错误，
  handler 调用直接 TypeError，客户端收到 500（且异常逃出 ASGI 应用，TestClient 默认配置下直接抛栈）。

已实测的两种绕过方式均正常：

```python
# 方式 1：显式 request_model（参数仍可注解为 dict）
@router.post("/", request_model=Item)
async def create(self, item: dict): ...

# 方式 2：参数注解为 BaseModel 子类（自动探测生效）
@router.post("/")
async def create(self, item: Item): ...
```

## 疑似原因

自动探测逻辑只在参数注解是 `BaseModel` 子类时才认定请求体参数；`dict` 注解被跳过后，
调用 `handler(**kwargs)` 时缺参。

## 修复方向（二选一）

1. **框架侧**：非路径/查询的 `dict` 注解参数接收原始 JSON dict（与 web.md 现有措辞一致）；
2. **文档侧**：web.md 删除 `item: dict` 示例，明确“请求体参数必须是 BaseModel 子类，或配合显式 `request_model`”。

即使选 2，缺参也应转成结构化错误响应（4xx/500 JSON），而不是未处理 TypeError——参见 doc/fet/001。
