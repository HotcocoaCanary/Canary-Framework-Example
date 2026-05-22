# 架构设计

## 目录

- [1. 技术决策](#1-技术决策)
- [2. 分层架构](#2-分层架构)
- [3. 模块划分](#3-模块划分)
- [4. 服务依赖图](#4-服务依赖图)
- [5. DBModule 设计](#5-dbmodule-设计)
- [6. Worker 线程](#6-worker-线程)
- [7. 中间件方案](#7-中间件方案)
- [8. 启动入口](#8-启动入口)
- [附录: 环境变量](#附录-环境变量)

---

## 1. 技术决策

| 决策点    | 选择                       | 理由                          |
|--------|--------------------------|-----------------------------|
| Web 框架 | FastAPI (cf.web.fastapi) | 异步原生, OpenAPI 自动生成          |
| ORM    | SQLModel                 | SQLAlchemy + Pydantic, 类型安全 |
| 向量存储   | PostgreSQL + pgvector    | 统一存储, 减少运维组件                |
| LLM 编排 | LangGraph                | 状态图清晰, 流式支持好                |
| 模型调用   | litellm                  | 统一接口, 多模型切换                 |
| 文档解析   | markitdown               | 多格式支持                       |
| 异步任务   | threading.Thread + Queue | 突破 GIL, 不阻塞主线程              |
| 对象存储   | OSS (S3 兼容)              | 独立于计算, 支持预览                 |
| 依赖注入   | Canary Framework         | 自动拓扑排序 + 依赖注入               |

---

## 2. 分层架构

```
┌──────────────────────────────────────────────┐
│  Router Layer    CF @router + FastAPI routes  │
├──────────────────────────────────────────────┤
│  Service Layer   @service 业务逻辑            │
├──────────────────────────────────────────────┤
│  Repository      DBService → Repo 工厂        │
├──────────────────────────────────────────────┤
│  Infrastructure  PostgreSQL / OSS / litellm   │
└──────────────────────────────────────────────┘
```

**关键规则:**

- Router 不直接调 Repo，必须经过 Service
- Repo 不标记 @service，通过 DBService 工厂方法获取
- 事务由 DBService.transaction() 管理

---

## 3. 模块划分

```
ly-ai-studio/
├── main.py
├── app/
│   ├── module/
│   │   ├── db_module/                    # @module DBModule
│   │   │   ├── service.py                # @service DBService
│   │   │   └── repository/
│   │   │       ├── kb_repo.py
│   │   │       ├── member_repo.py
│   │   │       ├── node_repo.py          # kb_nodes 统一 CRUD
│   │   │       ├── file_record_repo.py   # kb_file_records
│   │   │       ├── parse_repo.py
│   │   │       ├── chunk_repo.py
│   │   │       ├── session_repo.py
│   │   │       └── message_repo.py
│   │   │
│   │   ├── auth_module/                  # @module AuthModule
│   │   │   ├── service.py                # @service AuthService
│   │   │   └── depends.py               # get_current_user (FastAPI Depends)
│   │   │
│   │   ├── knowledge_module/             # @module KnowledgeModule
│   │   │   ├── service/
│   │   │   │   ├── kb_service.py         # @service @web(routers=[KbRouter])
│   │   │   │   ├── file_service.py       # @service @web(routers=[FileRouter])
│   │   │   │   └── parse_service.py      # @service @web(routers=[ParseRouter])
│   │   │   ├── router/
│   │   │   │   ├── kb_router.py
│   │   │   │   ├── file_router.py
│   │   │   │   └── parse_router.py
│   │   │   ├── state_machine.py          # 状态机
│   │   │   └── schema.py                 # Request/Response models
│   │   │
│   │   └── chat_module/                  # @module ChatModule
│   │       ├── service/
│   │       │   ├── session_service.py    # @service @web(routers=[SessionRouter])
│   │       │   └── rag_service.py        # @service @web(routers=[ChatRouter])
│   │       ├── router/
│   │       │   ├── session_router.py
│   │       │   └── chat_router.py
│   │       ├── graph.py                  # LangGraph 定义
│   │       └── schema.py
│   │
│   └── shared/
│       ├── worker/
│       │   ├── parse_worker.py           # @service ParseWorker
│       │   └── chunk_worker.py           # @service ChunkWorker
│       ├── oss/
│       │   └── client.py                 # @service OSSClient
│       ├── llm/
│       │   └── client.py                 # @service LLMClient
│       └── types.py                      # UserContext, 通用类型
```

---

## 4. 服务依赖图

```
DBService         (管理 session 和 Repo 工厂)
    ↑
AuthService       → deps=[DBService]
ParseWorker  → deps=[DBService, OSSClient]
ChunkWorker  → deps=[DBService, LLMClient]
    ↑
KbService         → deps=[DBService, AuthService, OSSClient]
FileService       → deps=[DBService, AuthService, OSSClient]
ParseService      → deps=[DBService, AuthService, ParseWorker, ChunkWorker]
    ↑
SessionService    → deps=[DBService]
RAGService        → deps=[DBService, LLMClient]

OSSClient, LLMClient (独立，无 deps)
```

---

## 5. DBModule 设计

```python
@service(name="DBService")
class DBService:
    """唯一对外暴露的数据库服务。
       其他 Service 通过 ctx.resolve(DBService) 获取,
       再调用工厂方法拿到对应 Repo。"""

    async def transaction(self) -> AsyncSession:
        """事务上下文, 同一事务内可操作多个 Repo"""
        ...

    # Repo 工厂方法
    def kb_repo(self, session: AsyncSession) -> KbRepo: ...

    def node_repo(self, session: AsyncSession) -> NodeRepo: ...

    def file_record_repo(self, session: AsyncSession) -> FileRecordRepo: ...

    def parse_repo(self, session: AsyncSession) -> ParseRepo: ...

    def chunk_repo(self, session: AsyncSession) -> ChunkRepo: ...

    def session_repo(self, session: AsyncSession) -> SessionRepo: ...

    def message_repo(self, session: AsyncSession) -> MessageRepo: ...
```

**使用示例:**

```python
async with db_service.transaction() as session:
    node_repo = db_service.node_repo(session)
    record_repo = db_service.file_record_repo(session)
    await node_repo.create(node)
    await record_repo.create(record)
    # 同一事务, 一起提交或回滚
```

---

## 6. Worker 线程

ParseWorker 和 ChunkWorker 均注册为 `@service`，纳入 CF 生命周期管理。各自在 `@on_start` 阶段启动独立线程和 event
loop，持有独立的 Queue 接收任务。

```
Main Thread (ParseService)     ParseWorker               ChunkWorker
         │                          │                          │
         │  upload files            │                          │
         ├─ submit(item) ────────→  ├─ _process_parse()        │
         │                          │   markitdown 解析         │
         │                          │   写 parsed_text          │
         │                          │   status → parsed        │
         │                          │                          │
         │  submit_chunk            │                          │
         ├─ submit(item) ──────────────────────────────────→  ├─ _process_chunk()
         │                          │                          │   文本分块
         │                          │                          │   embedding
         │                          │                          │   写 kb_chunks
         │                          │                          │   status → chunked
```

**关键规则：**

- 每个 Worker 自持独立 event loop，与主线程完全隔离
- 每个任务内用 `async with self.db_service.transaction()` 创建独立 session，不跨任务复用
- `@on_end` 向 Queue 投入哨兵值 `None`，线程收到后退出

## 7. 中间件方案

cf-web-fastapi 不内置中间件。使用 **FastAPI Depends** 实现认证注入：

```python
# auth_module/depends.py
from fastapi import Depends, Request, HTTPException


async def get_current_user(request: Request) -> UserContext:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(status_code=401)
    # 调用 Java 服务验证
    return await auth_service.validate(token)
```

Router 中使用:

```python
class KbRouter:
    @get("/api/v1/knowledge-bases")
    async def list_kbs(
            self,
            current: int = 1, size: int = 20,
            user: UserContext = Depends(get_current_user),
    ):
        ...
```

---

## 8. 启动入口

```python
# main.py
from cf.web.fastapi import WebCanary
from app.module.db_module.module import DBModule
from app.module.auth_module.module import AuthModule
from app.module.knowledge_module.module import KnowledgeModule
from app.module.chat_module.module import ChatModule


@web(routers=[])
@module(name="AppModule", services=[
    DBModule, AuthModule, KnowledgeModule, ChatModule,
])
class AppModule:
    @get("/health")
    async def health(self):
        return {"status": "ok"}


if __name__ == "__main__":
    WebCanary(AppModule, log_level="info").start()
```

启动流程: WebCanary → Canary.start() (拓扑排序初始化) → 注册 Router → uvicorn.run()

---

## 附录: 环境变量

| 变量               | 说明              | 默认值                        |
|------------------|-----------------|----------------------------|
| DATABASE_URL     | PostgreSQL 连接串  | `postgresql+asyncpg://...` |
| OSS_ENDPOINT     | OSS 端点          | —                          |
| OSS_ACCESS_KEY   | OSS AccessKey   | —                          |
| OSS_SECRET_KEY   | OSS SecretKey   | —                          |
| OSS_BUCKET       | OSS Bucket      | `ly-ai-studio`             |
| OSS_BASE_URL     | OSS 访问前缀        | —                          |
| JAVA_BASE_URL    | Java 微服务地址      | —                          |
| LITELLM_API_BASE | litellm 网关地址    | —                          |
| LITELLM_API_KEY  | litellm API Key | —                          |
| EMBEDDING_MODEL  | Embedding 模型名   | `qwen-embedding`           |
| LOG_LEVEL        | 日志级别            | `INFO`                     |
