# 开发规范

## 目录

- [1. 项目结构](#1-项目结构)
- [2. 命名规范](#2-命名规范)
- [3. 模块组织](#3-模块组织)
- [4. Service 设计](#4-service-设计)
- [5. Router 设计](#5-router-设计)
- [6. 依赖注入](#6-依赖注入)
- [7. DB 访问](#7-db-访问)
- [8. 错误处理](#8-错误处理)
- [9. 日志](#9-日志)
- [10. 配置](#10-配置)
- [11. 测试](#11-测试)
- [12. 代码检查清单](#12-代码检查清单)

---

## 1. 项目结构

```
ly-ai-studio/
├── main.py                       # 入口，WebCanary(AppModule).start()
├── app/
│   ├── module/
│   │   ├── db_module/            # 数据库模块
│   │   │   ├── module.py         # @module("DBModule")
│   │   │   ├── service.py        # @service("DBService")
│   │   │   └── repository/       # Repo 层（普通类）
│   │   │       ├── kb_repo.py
│   │   │       └── ...
│   │   ├── knowledge_module/     # 业务模块
│   │   │   ├── module.py
│   │   │   ├── service/
│   │   │   │   ├── kb_service.py     # @service + @web
│   │   │   │   └── file_service.py
│   │   │   ├── router/
│   │   │   │   ├── kb_router.py      # @router
│   │   │   │   └── file_router.py
│   │   │   ├── schema.py             # Request/Response models
│   │   │   └── state_machine.py      # 业务状态机
│   │   └── auth_module/
│   └── shared/
│       ├── type/
│       ├── oss/
│       └── llm/
├── tests/                         # 测试
├── doc/
└── pyproject.toml
```

**规则：**
- 每个模块一个目录，包含 `module.py` 入口
- Service 放 `service/`，Router 放 `router/`，Schema 放 `schema/`
- 跨模块共享的类型/工具放 `app/shared/`

---

## 2. 命名规范

### 文件/目录

| 类型         | 规范                    | 示例                 |
|------------|-----------------------|--------------------|
| 模块目录       | `snake_case_module`   | `knowledge_module` |
| Service 文件 | `{domain}_service.py` | `kb_service.py`    |
| Router 文件  | `{domain}_router.py`  | `kb_router.py`     |
| Schema 文件  | `schema.py`           |                    |
| Repo 文件    | `{table}_repo.py`     | `kb_repo.py`       |

### 类/方法

| 类型                      | 规范                          | 示例                        |
|-------------------------|-----------------------------|---------------------------|
| Service 类               | `{Domain}Service`           | `KbService`               |
| Router 类                | `{Domain}Router`            | `KbRouter`                |
| Config 类                | `{Domain}Config`            | `DBConfig`                |
| Request Schema          | `{Action}{Resource}Request` | `CreateKbRequest`         |
| Response Schema         | `{Resource}Response`        | `KbResponse`              |
| Service name (@service) | `"{Domain}Service"`         | `"KbService"`             |
| Router prefix           | `/api/v1/{resource}`        | `/api/v1/knowledge-bases` |

---

## 3. 模块组织

每个业务模块的标准结构：

```python
# module.py
from cf import module
from .service.kb_service import KbService
from .service.file_service import FileService

@module(name="KnowledgeModule", services=[KbService, FileService])
class KnowledgeModule:
    pass
```

```python
# service/kb_service.py
from cf import service, on_init, ServiceContext
from cf.web.fastapi import web
from .router.kb_router import KbRouter

@web(routers=[KbRouter])
@service(name="KbService", deps=[DBService])
class KbService:
    @on_init
    def init(self, ctx: ServiceContext):
        pass

    async def create_kb(self, user, data): ...
    async def list_user_kbs(self, user, page, size): ...
```

```python
# router/kb_router.py
from cf.web.fastapi import router, get, post, RouterContext
from app.module.auth_module.depends import get_current_user

@router(prefix="/api/v1/knowledge-bases")
class KbRouter:
    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service

    @post("/")
    async def create(self, req: CreateKbRequest,
                     user=Depends(get_current_user)):
        return await self.svc.create_kb(user, req)
```

```python
# schema.py
from pydantic import BaseModel

class CreateKbRequest(BaseModel):
    name: str
    permission: str = "private"

class KbResponse(BaseModel):
    id: str
    name: str
    permission: str
    created_at: str
```

---

## 4. Service 设计

### 原则

1. **单一职责**：一个 Service 做一件事
2. **通过 deps 声明依赖**：不要手动 import 后 new
3. **初始化放 @on_init**：不要在 `__init__` 做重逻辑
4. **方法返回业务对象**：不要返回 dict，用 Schema

### 反例

```python
# ❌ 不要这样
class UserService:
    def __init__(self):
        self.db = DBService()          # 手动 new
        self.db.connect()              # 构造时做重逻辑

    def get(self, id):
        return {"name": "Alice"}       # 返回 dict
```

### 正例

```python
# ✅ 应该这样
@service(name="UserService", deps=[DBService])
class UserService:
    @on_init
    def init(self, ctx: ServiceContext):
        pass                           # 轻量初始化

    def get(self, id: int) -> UserResponse:
        user = self.db_service.query(id)
        return UserResponse.from_orm(user)
```

---

## 5. Router 设计

### 原则

1. **Router 绑定到 Service**：通过 `@web(routers=[...])` 声明
2. **Router 只做参数校验和调用**：不写业务逻辑
3. **用 Depends 注入认证信息**：`user = Depends(get_current_user)`
4. **用 Schema 声明输入输出**：让 FastAPI 自动生成文档

### 反例

```python
# ❌ Router 里写业务逻辑
class UserRouter:
    @get("/{id}")
    async def get(self, id: int):
        user = await db.execute(f"SELECT * FROM users WHERE id={id}")
        return {"name": user[1]}       # 直接查数据库
```

### 正例

```python
# ✅ Router 只做路由和校验
class UserRouter:
    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service

    @get("/{user_id}", response_model=R[UserResponse])
    async def get(self, user_id: int,
                  user=Depends(get_current_user)):
        result = await self.svc.get_user(user_id)
        return R(data=result)
```

---

## 6. 依赖注入

### 规则

1. **只在 Service 间注入**：Router → Service → Repo
2. **Repo 不通过 DI 获取**：通过 `DBService.repo_name(session)` 工厂方法
3. **注入属性名自动推导**：`CamelCase` → `snake_case`

```python
# ✅ Service 通过 deps 获取
@service(name="KbService", deps=[DBService, OSSClient])
class KbService:
    # self.db_service   → DBService 实例
    # self.oss_client   → OSSClient 实例
    ...

# ✅ Router 通过 ctx.resolve 获取
class KbRouter:
    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service               # 绑定的 Service
        self.other = ctx.resolve(OtherService)  # 其他 Service

# ✅ Repo 通过 DBService 工厂获取
async def some_method(self):
    async with self.db_service.transaction() as session:
        kb_repo = self.db_service.kb_repo(session)
        node_repo = self.db_service.node_repo(session)
```

---

## 7. DB 访问

### 规则

1. **所有 DB 操作通过 Repo**：Service 不直接写 SQL
2. **事务由 DBService.transaction() 管理**：同一事务内多个 Repo 一起提交
3. **使用 SQLModel 异步 API**：`select()`, `session.exec()`, `session.add()`

```python
# ✅ 标准用法
async def create_kb_with_folder(self, user, data):
    async with self.db_service.transaction() as session:
        kb_repo = self.db_service.kb_repo(session)
        node_repo = self.db_service.node_repo(session)

        kb = await kb_repo.create(KnowledgeBase(...))
        folder = await node_repo.create(KbNode(node_type=None, ...))
        # 同一事务，一起提交或回滚
```

### 禁止

- ❌ Service 中直接 `session.execute(text("SELECT ..."))`
- ❌ 跨 Service 共享 session（session 是线程不安全的）
- ❌ 忘记 `await` (SQLModel 是异步的)

---

## 8. 错误处理

### 业务错误

使用 HTTPException 或自定义异常：

```python
from app.common.errors import InvalidStateError

if not can_chunk(record.status):
    raise InvalidStateError(
        status_code=409,
        message=f"文件 {fid} 状态为 {record.status}，需要先解析"
    )
```

### 规则

1. 用户可见的权限校验 → 403
2. 资源不存在 → 404
3. 状态机冲突 → 409
4. 参数验证错误 → Pydantic 自动 422
5. 未预期的错误 → 500，记录日志

```python
# ✅ 明确的错误
if kb.created_by != user.user_id:
    raise HTTPException(status_code=403, detail="仅创建者可操作")

# ✅ 业务状态错误
if record.status != "parsed":
    raise InvalidStateError(409, "需要先解析")
```

---

## 9. 日志

### 使用方式

```python
import logging
logger = logging.getLogger(__name__)
```

### 规则

1. **每个模块有自己的 logger**：`logging.getLogger(__name__)`
2. **入口文件配 `logging.basicConfig()`**：设置格式
3. **使用合适的级别**：
   - `DEBUG`: 开发调试信息
   - `INFO`: 关键业务节点（创建、删除、状态变更）
   - `WARNING`: 可恢复的异常
   - `ERROR`: 需要关注的错误

```python
@service(name="KbService", deps=[DBService])
class KbService:
    @on_init
    def init(self, ctx):
        logger.info("KbService initialized")

    async def create_kb(self, user, data):
        logger.info(f"Creating KB: name={data.name}, user={user.user_id}")
        try:
            kb = await self._do_create(user, data)
            logger.info(f"KB created: id={kb.id}")
            return kb
        except Exception as e:
            logger.error(f"Failed to create KB: {e}")
            raise
```

---

## 10. 配置

### 定义

```python
@config
class KbConfig:
    max_file_size: int = 104857600     # 100 MB
    chunk_size: int = 512
    chunk_overlap: int = 64
```

### 环境变量

| 变量 | 说明 |
|------|------|
| DATABASE_URL | PostgreSQL 连接串 |
| OSS_ENDPOINT | OSS 端点 |
| JAVA_BASE_URL | Java 微服务地址 |
| LITELLM_API_BASE | litellm 地址 |
| LOG_LEVEL | 日志级别 |

在 `.env` 文件中配置，框架自动加载。

---

## 11. 测试

### 结构

```
tests/
├── conftest.py              # fixtures: test_db, test_client
├── test_kb_service.py       # KB 业务逻辑测试
├── test_rag_service.py      # RAG 流程测试
└── test_api.py              # 接口集成测试
```

### 规则

1. 用 `pytest` + `pytest-asyncio`
2. Service 测试用真实 DB（测试库）
3. 外部依赖（Java/OSS/LLM）用 mock
4. 状态机用参数化测试覆盖所有转换

---

## 12. 代码检查清单

提交前确认：

- [ ] Service 用 `@service` 装饰，name 全局唯一
- [ ] Module 用 `@module` 装饰，包含的 Service 在 `services` 列表中
- [ ] 依赖通过 `deps=[...]` 声明，不手动 new
- [ ] Router 通过 `@web(routers=[...])` 绑定到 Service
- [ ] `@on_init` 只做初始化，不做长时间阻塞
- [ ] 请求/响应用 Pydantic Schema 定义类型
- [ ] DB 操作通过 Repo，不直接写 SQL
- [ ] 事务通过 `DBService.transaction()` 管理
- [ ] 错误返回合适的 HTTP 状态码
- [ ] 日志用 `logging.getLogger(__name__)`，级别恰当
- [ ] 环境变量在 `.env` 中配置，不在代码中硬编码
