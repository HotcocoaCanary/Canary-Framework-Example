# PigX/Aliyun 模块化重构设计

## 概述

将 `app/shared/pigx/` 和 `app/shared/aliyun/` 从普通工具模块重构为标准 CF 模块，统一纳入依赖注入体系。

- **PigX 模块**: 提供 `AuthService`，统一管理认证逻辑和 `get_current_user` FastAPI 依赖
- **Aliyun 模块**: 对现有 `OSSClient` 服务加模块包装，便于后续扩展其他阿里云服务

---

## 1. 目录结构变化

### 现有结构

```
app/shared/
├── pigx/
│   └── auth.py          # get_current_user + 内联 HTTP 调用
├── aliyun/
│   └── oss.py            # @service OSSClient (独立服务)
├── llm/
│   └── client.py         # @service LLMClient (独立服务)
└── worker/
    ├── parse_worker.py   # @service ParseWorker
    └── chunk_worker.py   # @service ChunkWorker
```

### 目标结构

```
app/shared/               
├── pigx/                 # PigX 认证模块 (从 app/shared/pigx/auth.py 重构)
│   ├── __init__.py
│   ├── module.py         # @module PigXModule
│   ├── service.py        # @service AuthService
│   └── depends.py        # get_current_user (FastAPI Depends)
├── aliyun/               # 阿里云模块 (从 app/shared/aliyun/oss.py + module 壳)
│   ├── __init__.py
│   ├── module.py         # @module AliyunModule
│   └── oss.py            # @service OSSClient (不变)
├── llm/
│   └── client.py         # 不变
└── worker/
    ├── parse_worker.py   # 不变
    └── chunk_worker.py   # 不变
```

---

## 2. PigX 模块设计

### 2.1 文件说明

```
app/shared/pigx/
├── __init__.py
├── module.py       # @module PigXModule
├── service.py      # @service AuthService
└── depends.py      # get_current_user (FastAPI Depends 入口)
```

### 2.2 类设计

#### AuthConfig (`@config`)

```python
@config
class AuthConfig:
    pigx_base: str = ""
```

- 字段: `pigx_base` — Java 适配器地址（对应 `.env` 中的 `PIGX_BASE`）

#### AuthService (`@service`)

```python
import httpx
import logging
from fastapi import HTTPException
from cf import service, on_init, on_end, ServiceContext, config
from app.common.types import UserContext

logger = logging.getLogger(__name__)

@service(name="AuthService", config=AuthConfig)
class AuthService:
    @on_init
    def init(self, ctx: ServiceContext):
        self._base_url = ctx.config.pigx_base
        self._http_client = httpx.AsyncClient(timeout=10.0)

    @on_end
    async def end(self):
        await self._http_client.aclose()

    async def get_current_user(self, token: str, product_id: str, tenant_id: str) -> UserContext:
        """调用 Java 适配器验证 token，返回 UserContext"""
        if not self._base_url:
            raise HTTPException(status_code=500, detail="PIGX_BASE 未配置")

        try:
            response = await self._http_client.get(
                f"{self._base_url}/ai-studio-adapter/v1/java-adapter/auth/current-user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "PRODUCT-ID": product_id,
                    "TENANT-ID": tenant_id,
                },
            )
            data = response.json()
            if data.get("code") != 0:
                raise HTTPException(status_code=401, detail="认证失败")

            user_data = data["data"]
            return UserContext(
                user_id=user_data.get("userId", ""),
                username=user_data.get("username", ""),
                tenant_id=user_data.get("tenantId"),
                roles=user_data.get("authorities", []),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("认证请求异常: %s", e)
            raise HTTPException(status_code=401, detail="认证失败")
```

**职责**:
- 封装与 Java 适配器的 HTTP 通信
- 管理 `httpx.AsyncClient` 生命周期（通过 `@on_end` 正确关闭）
- 可被其他 CF 服务通过 DI 引用（如 `deps=[AuthService]`）

#### `get_current_user` (`depends.py`)

```python
from fastapi import Request, HTTPException
from app.shared.pigx.service.service import AuthService


async def get_current_user(request: Request) -> UserContext:
    """FastAPI Depends，从请求提取 token 并通过 AuthService 验证"""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    product_id = request.headers.get("PRODUCT-ID", "")
    tenant_id = request.headers.get("TENANT-ID", "")

    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    # 从 FastAPI app.state 获取 CF 注册表，解析 AuthService
    registry = request.app.state.cf_registry
    auth_service: AuthService = registry.get_instance(AuthService)
    return await auth_service.get_current_user(token, product_id, tenant_id)
```

### 2.3 关键技术决策: `get_current_user` 如何获取 `AuthService` 实例

**问题**: FastAPI 的 `Depends(get_current_user)` 是一个独立函数，不在 CF 的 DI 容器内，无法通过 `@service.deps` 自动注入依赖。

**方案对比**:

| 方案 | 描述 | 全局状态 | 需改 CF | 可测试性 |
|------|------|:---:|:---:|:---:|
| A | 模块级单例 (`_auth_service` 全局变量) | 有 | 否 | 差 |
| B | `request.app.state.cf_registry` | **无** | **是** (1 行) | **好** |
| C | CF 框架完整扩展 | 无 | 是 (大量) | 最好 |

**采用方案 B: `request.app.state.cf_registry`**

CF 框架改造（`lib/canary_framework/cf/web/fastapi/web_canary.py`，仅 1 行）:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await canary._startup()
    app.state.cf_registry = canary._registry   # ← 新增: 暴露 Registry
    _register_routes(app, canary._registry)
    yield
    await canary._shutdown()
```

`get_current_user` 通过 `request.app.state.cf_registry.get_instance(AuthService)` 从 DI 容器获取服务实例，**零全局变量**。

**流程**:

```
Canary._startup()
  → init AuthService (含 httpx client)      [启动阶段]
  → app.state.cf_registry = registry        [暴露 Registry]
  → 注册路由                                  [FastAPI 就绪]

Request → Depends(get_current_user)
  → request.app.state.cf_registry
  → get_instance(AuthService)               [每请求解析]
  → auth_service.get_current_user(...)
```

**为什么选 B 而不是 A**:
- 方案 A 的全局变量在测试中难以替换，方案 B 只需在测试 `Request` 的 `app.state` 上设置 mock registry
- 方案 A 引入了隐式耦合（`depends.py` 依赖 `service.py` 的全局变量状态），方案 B 依赖 CF 框架的显式 Registry API
- 1 行框架改动换来的是一个通用能力：任何 `Depends` 函数都可以从 Registry 获取任意 CF 服务

### 2.4 模块定义 (`module.py`)

```python
from app.shared.pigx.service.service import AuthService
from cf import module


@module(name="PigXModule", services=[AuthService])
class PigXModule:
    pass
```

### 2.5 使用方式 (不变)

路由器中的使用方式**完全不变**:

```python
from app.common.depends import get_current_user


@post("/chat/completions")
async def chat_completions(self, req: ChatCompletionRequest, user=Depends(get_current_user)):
    return await self.svc.chat_completions(user, req)
```

仅 import 路径从 `app.shared.pigx.auth` 变为 `app.shared.pigx.depends`。

---

## 3. Aliyun 模块设计

### 3.1 文件说明

```
app/shared/aliyun/
├── __init__.py
├── module.py       # @module AliyunModule
└── oss.py           # @service OSSClient (现有代码，不动)
```

### 3.2 类设计

#### OSSConfig (`@config`) — 不变

```python
@config
class OSSConfig:
    oss_endpoint: str = ""
    oss_region: str = ""
    oss_bucket: str = ""
    oss_access_key: str = ""
    oss_secret_key: str = ""
```

#### OSSClient (`@service`) — 不变

现有代码完全不变，仅移动到新位置。

#### 模块定义 (`module.py`)

```python
from app.module.aliyun_module.oss import OSSClient
from cf import module

@module(name="AliyunModule", services=[OSSClient])
class AliyunModule:
    pass
```

### 3.3 扩展点

后续可在此模块下添加其他阿里云服务:

```
app/shared/aliyun/
├── module.py
├── oss.py           # OSSClient
├── sms.py           # SMSClient (future)
└── green.py         # ContentModerationClient (future)
```

---

## 4. AppModule 变化 + CF 框架改动

### 4.1 CF 框架改动 (`web_canary.py`)

**文件**: `lib/canary_framework/cf/web/fastapi/web_canary.py`

```diff
 async def lifespan(app: FastAPI):
     await canary._startup()
+    app.state.cf_registry = canary._registry
     _register_routes(app, canary._registry)
     yield
     await canary._shutdown()
```

仅增加 1 行，将 Registry 暴露到 `app.state`，使 `Depends` 函数可以通过 `request.app.state.cf_registry.get_instance(ServiceClass)` 获取任意 CF 服务。

### 4.2 main.py 变化

```python
from app.shared.pigx.module import PigXModule
from app.shared.aliyun.module import AliyunModule

@web(routers=[])
@module(
    name="AppModule",
    services=[
        DBModule,
        PigXModule,       # 新增
        AliyunModule,     # 新增 (替代 OSSClient)
        KnowledgeModule,
        ChatModule,
        LLMClient,        # 保留 (无模块包装的纯服务)
        ParseWorker,
        ChunkWorker,
    ],
)
class AppModule:
    ...
```

`AppModule.services` 中:
- `PigXModule` 替代隐式 auth 逻辑，CF 递归收集 `AuthService`
- `AliyunModule` 替代 `OSSClient`，CF 递归收集模块内服务
- `LLMClient`, `ParseWorker`, `ChunkWorker` 暂不包装模块

---

## 5. 影响范围

### 需修改的文件

| 文件 | 改动 |
|------|------|
| `lib/canary_framework/cf/web/fastapi/web_canary.py` | +1 行: `app.state.cf_registry = canary._registry` |
| `main.py` | 新增 `PigXModule`, `AliyunModule` 导入，更新 `services` 列表 |
| `app/shared/pigx/` | 新建 4 个文件 (`__init__.py`, `module.py`, `service.py`, `depends.py`) |
| `app/shared/aliyun/module.py` | 新建 1 个文件 (模块壳) |
| `app/shared/pigx/auth.py` | 删除 (逻辑已迁移) |
| 所有 `from app.shared.pigx.auth import get_current_user` | 改为 `from app.shared.pigx.depends import get_current_user` |
| 所有 `from app.shared.aliyun.oss import OSSClient` | 不变 (路径未变) |

### 不受影响的文件

- 所有 `*_service.py` — 通过 DI 获取服务，不感知模块位置
- 所有 `*_router.py` — 仅 import 路径变化
- 所有 `*_repo.py` — 不引用 auth/oss
- `app/common/` — 不引用 auth/oss
- `.env` — 环境变量不变
- `app/shared/aliyun/oss.py` — 代码完全不变，仅在其旁边新增 `module.py`

---

## 6. 实施步骤

### Step 0: CF 框架改动 (1 行)

修改 `lib/canary_framework/cf/web/fastapi/web_canary.py`，在 lifespan 中加一行:

```python
app.state.cf_registry = canary._registry
```

### Step 1: 创建 PigX 模块

1. 在 `app/shared/pigx/` 下新建: `__init__.py`, `service.py`, `depends.py`, `module.py`
2. 逻辑从 `app/shared/pigx/auth.py` 迁移: HTTP 调用 → `AuthService`, 提取 header → `depends.py`
3. 删除旧的 `app/shared/pigx/auth.py`

### Step 2: 创建 Aliyun 模块壳

1. 在 `app/shared/aliyun/` 下新建: `module.py` (仅 6 行)
2. `oss.py` 不需要任何改动

### Step 3: 更新所有 import

1. `main.py` — 添加 `PigXModule`, `AliyunModule`
2. 全局替换: `from app.shared.pigx.auth import get_current_user` → `from app.shared.pigx.depends import get_current_user`
3. Aliyun 相关 import 不变

### Step 4: 验证

1. 启动 `python main.py`
2. 测试 `/health`
3. `curl -X POST http://127.0.0.1:8000/v1/chat/completions ...` 验证 auth 链路
4. 测试知识库文件上传验证 OSS

---

## 7. 环境变量映射

| `.env` 变量 | 模块 | Config 类 | 字段 |
|-------------|------|-----------|------|
| `PIGX_BASE` | PigXModule | `AuthConfig` | `pigx_base` |
| `OSS_ENDPOINT` | AliyunModule | `OSSConfig` | `oss_endpoint` |
| `OSS_REGION` | AliyunModule | `OSSConfig` | `oss_region` |
| `OSS_BUCKET` | AliyunModule | `OSSConfig` | `oss_bucket` |
| `OSS_ACCESS_KEY` | AliyunModule | `OSSConfig` | `oss_access_key` |
| `OSS_SECRET_KEY` | AliyunModule | `OSSConfig` | `oss_secret_key` |

> 注: pydantic-settings 默认将 `PIGX_BASE` (大写+下划线) 映射到 `pigx_base` (小写)，无需额外配置。
