# CF 框架使用文档

## 目录

- [1. 概述](#1-概述)
- [2. 核心概念](#2-核心概念)
- [3. 快速开始](#3-快速开始)
- [4. API 参考](#4-api-参考)
- [5. Web 层 (cf.web.fastapi)](#5-web-层-cfwebfastapi)
- [6. 完整示例](#6-完整示例)

---

## 1. 概述

CF (Canary Framework) 是一个 Python 异步服务框架，核心能力：

- **依赖注入**：`deps` 声明依赖，框架自动按拓扑顺序初始化并注入
- **生命周期管理**：`@on_init` → `@on_start` → `@on_end`
- **配置管理**：基于 Pydantic Settings，支持级联 `.env` 查找
- **Web 集成** (cf.web.fastapi)：`@router` 类 + `@get/@post` 装饰器，自动注册到 FastAPI

---

## 2. 核心概念

```
Canary(target).start()
  └─ 递归收集 @service 和 @module
       ├─ 拓扑排序（基于 deps 计算）
       ├─ 自动注入 deps → self.xxx（CamelCase → snake_case）
       ├─ 按序调用 @on_init → @on_start
       └─ shutdown 时逆序调用 @on_end
```

- **Service**：最小逻辑单元，声明依赖和生命周期
- **Module**：Service 的组合容器，本身也有生命周期
- **Canary**：启动器，接收一个 Service 或 Module 类型
- **WebCanary**：Web 启动器，= Canary + FastAPI + uvicorn

---

## 3. 快速开始

### 3.1 创建项目

```
my-app/
├── main.py
├── service/
│   ├── db_service.py
│   └── user_service.py
└── pyproject.toml
```

pyproject.toml:
```toml
[project]
name = "my-app"
requires-python = ">=3.12"
dependencies = ["cf[web]>=0.1.0"]

[tool.uv.sources]
cf = { path = "../lib/canary_framework", editable = true }
```

### 3.2 定义配置

```python
from cf import config

@config
class DBConfig:
    url: str = "postgresql://localhost:5432/mydb"
    pool_size: int = 10
```

### 3.3 定义 Service

```python
from cf import service, on_init, on_start, on_end
from cf import ServiceContext

@service(name="DBService", config=DBConfig)
class DBService:
    @on_init
    def init(self, ctx: ServiceContext):
        print(f"connecting to {ctx.config.url}")

    @on_start
    def start(self):
        print("DBService ready")

    @on_end
    def end(self):
        print("DBService shutdown")

    def query(self, sql: str):
        pass  # 实际查询逻辑
```

### 3.4 声明依赖

```python
from service.db_service import DBService

@service(name="UserService", deps=[DBService])
class UserService:
    # 框架自动注入: self.db_service = DBService 实例

    @on_init
    def init(self, ctx: ServiceContext):
        pass

    def get_user(self, user_id: int):
        return self.db_service.query(f"SELECT * FROM users WHERE id={user_id}")
```

### 3.5 启动

```python
from cf import Canary

if __name__ == "__main__":
    Canary(UserService).start()          # 单独启动一个 Service
    # 或
    Canary(AppModule).start()            # 启动 Module
```

---

## 4. API 参考

### 4.1 `@config`

将普通类转为 Pydantic Settings 类，支持从 `.env` 加载值。

```python
from cf import config

@config
class MyConfig:
    host: str = "localhost"      # 有默认值
    port: int                     # 无默认值 → 必须从 env 获取
    api_key: str = ""            # 可选
```

- 类属性自动转为 Settings 字段
- 类型注解决定验证规则
- 实例化时框架自动传入 `_env_file` 参数
- 支持所有 Pydantic BaseSettings 能力

### 4.2 `@service`

```python
@service(
    name: str,                     # 必填，全局唯一名
    *,
    config: type | None = None,    # @config 类
    deps: list[type] | None = None, # 依赖的其他 @service 类
    config_file_path: str | None = None,  # .env 路径
)
```

**自动注入规则**：`deps` 中的类在 `@on_init` 之前自动注入到 self 上。

```
DepClassName          → self.dep_class_name
DBService             → self.db_service
DataSetAdminService   → self.data_set_admin_service
```

### 4.3 `@module`

```python
@module(
    name: str,
    *,
    config: type | None = None,
    services: list[type] | None = None,  # 子 Service / Module 列表
    config_file_path: str | None = None,
)
```

Module 是 Service 的超集 — 有相同的生命周期，额外可包含子服务。

### 4.4 生命周期装饰器

```python
@on_init       # def method(self, ctx: ServiceContext | ModuleContext)
@on_start      # def method(self)
@on_end        # def method(self)
```

- 方法可以是同步或异步 (async def)
- 也可以用命名约定（不装饰），框架会查找 `on_init`/`on_start`/`on_end` 方法名
- 调用顺序：所有 Service 的 `on_init` → 所有 Service 的 `on_start`
- Shutdown: 逆序调用 `on_end`

### 4.5 `Canary`

```python
Canary(
    target: type,              # @service 或 @module 类
    *,
    config_file_path: str = ".env",
    log_level: str = "INFO",   # DEBUG/INFO/WARNING/ERROR
    log_format: str = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
```

| 方法 | 说明 |
|------|------|
| `start()` | 启动所有服务（同步，内部用 asyncio.run） |
| `stop()` | 关闭所有服务（逆序） |

### 4.6 `ServiceContext` / `ModuleContext`

`@on_init` 方法的参数，提供 `ctx.config` 访问配置。

```python
class ServiceContext:
    @property
    def config(self) -> object: ...
```

---

## 5. Web 层 (cf.web.fastapi)

### 5.1 `@web`

标记 Service/Module 对外提供 HTTP 接口。

```python
from cf.web.fastapi import web

@web(routers=[UserRouter])         # 声明 router 列表
@service(name="UserService", deps=[DBService])
class UserService:
    ...
```

### 5.2 `@router`

定义一组 HTTP 路由。

```python
from cf.web.fastapi import router, get, post, RouterContext

@router(prefix="/api/v1/users")
class UserRouter:

    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service          # 绑定到 UserService
        self.db  = ctx.service.db_service   # 直接访问注入的依赖

    @get("/{user_id}")
    async def get_user(self, user_id: int):
        return await self.svc.get_user(user_id)

    @post("/")
    async def create_user(self, name: str):
        ...
```

### 5.3 HTTP 方法装饰器

```python
@get(path, **kwargs)     # GET
@post(path, **kwargs)    # POST
@put(path, **kwargs)     # PUT
@delete(path, **kwargs)  # DELETE
@patch(path, **kwargs)   # PATCH
```

- `path`: URL 路径，支持 FastAPI 路径参数 (`{id}`)
- `**kwargs`: 透传给 FastAPI，如 `response_model`, `status_code`, `tags`

### 5.4 `RouterContext`

传入 `@router` 类构造函数的参数。

```python
class RouterContext:
    service: object                   # 绑定的 Service/Module 实例

    def resolve(self, svc_cls: type[T]) -> T:
        """按类查找任意已注册的 Service 实例"""
```

### 5.5 `WebCanary`

```python
from cf.web.fastapi import WebCanary

WebCanary(
    target: type,
    *,
    config_file_path: str = ".env",
    log_level: str = "INFO",
    log_format: str = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
```

| 方法 | 说明 |
|------|------|
| `start(host="0.0.0.0", port=8000)` | 启动 Canary + 注册路由 + uvicorn |
| `stop()` | 关闭 |

---

## 6. 完整示例

```
my-app/
├── main.py
├── service/
│   ├── db_service.py
│   ├── user_service.py
│   └── user_router.py
└── pyproject.toml
```

### service/db_service.py

```python
from cf import service, on_init, on_start, on_end, ServiceContext

@service(name="DBService")
class DBService:
    @on_init
    def init(self, ctx: ServiceContext):
        self.connected = True

    def query(self, sql: str) -> list:
        return [{"id": 1, "name": "Alice"}]
```

### service/user_service.py

```python
from cf import service, on_init, ServiceContext
from cf.web.fastapi import web
from service.db_service import DBService
from service.user_router import UserRouter

@web(routers=[UserRouter])
@service(name="UserService", deps=[DBService])
class UserService:
    @on_init
    def init(self, ctx: ServiceContext):
        pass

    def get_user(self, user_id: int):
        return self.db_service.query(f"SELECT * FROM users WHERE id={user_id}")
```

### service/user_router.py

```python
from cf.web.fastapi import router, get, RouterContext

@router(prefix="/api/v1/users")
class UserRouter:
    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service

    @get("/{user_id}")
    async def get_user(self, user_id: int):
        return self.svc.get_user(user_id)
```

### main.py

```python
from cf.web.fastapi import WebCanary
from service.user_service import UserService

if __name__ == "__main__":
    WebCanary(UserService, log_level="info").start()
```

运行：
```bash
uv run python main.py
# 访问 http://localhost:8000/api/v1/users/1
```
