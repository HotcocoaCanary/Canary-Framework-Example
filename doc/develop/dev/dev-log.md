# ly-ai-studio 开发文档

## 开发概述

- **开发日期**: 2026-05-20
- **版本**: v0.1.0
- **技术栈**: CF (Canary Framework) + FastAPI + SQLModel + LangGraph + litellm + pgvector

---

## 1. 项目结构

```
ly-ai-studio/
├── main.py                          # 入口，WebCanary(AppModule).start()
├── pyproject.toml                   # 项目配置和依赖
├── .env                             # 环境变量
├── app/
│   ├── __init__.py
│   ├── module/
│   │   ├── db_module/               # 数据库模块
│   │   │   ├── module.py            # @module DBModule
│   │   │   ├── service.py           # @service DBService
│   │   │   ├── models.py            # SQLModel 表定义 (8 张表)
│   │   │   └── repository/          # Repo 层 (8 个 Repo)
│   │   │       ├── kb_repo.py
│   │   │       ├── member_repo.py
│   │   │       ├── node_repo.py
│   │   │       ├── file_record_repo.py
│   │   │       ├── parse_repo.py
│   │   │       ├── chunk_repo.py
│   │   │       ├── session_repo.py
│   │   │       └── message_repo.py
│   │   ├── auth_module/             # 认证模块
│   │   │   ├── module.py            # @module AuthModule
│   │   │   ├── service.py           # @service AuthService
│   │   │   └── depends.py           # FastAPI Depends (get_current_user)
│   │   ├── knowledge_module/        # 知识库模块
│   │   │   ├── module.py            # @module KnowledgeModule
│   │   │   ├── service/
│   │   │   │   ├── kb_service.py    # @service KbService
│   │   │   │   ├── file_service.py  # @service FileService
│   │   │   │   └── parse_service.py # @service ParseService
│   │   │   ├── router/
│   │   │   │   ├── kb_router.py     # @router /api/v1/knowledge-bases
│   │   │   │   ├── file_router.py   # @router /api/v1/knowledge-bases/file-op
│   │   │   │   └── parse_router.py  # @router /api/v1/knowledge-bases/file-op (parse)
│   │   │   ├── schema.py            # Request/Response Pydantic models
│   │   │   └── state_machine.py     # 文件处理状态机
│   │   └── chat_module/             # 问答模块
│   │       ├── module.py            # @module ChatModule
│   │       ├── service/
│   │       │   ├── session_service.py  # @service SessionService
│   │       │   └── rag_service.py      # @service RAGService
│   │       ├── router/
│   │       │   ├── session_router.py   # @router /api/v1/sessions
│   │       │   └── chat_router.py      # @router /v1
│   │       ├── graph.py             # LangGraph RAG 编排
│   │       └── schema.py            # Chat Request/Response models
│   └── shared/
│       ├── types.py                 # UserContext, PageResult
│       ├── errors.py                # AppError, NotFoundError, etc.
│       ├── response.py              # R[T] 统一响应, PageR
│       ├── registry.py              # 全局服务注册表
│       ├── oss/
│       │   └── client.py            # @service OSSClient
│       ├── llm/
│       │   └── client.py            # @service LLMClient
│       └── worker/
│           ├── parse_worker.py      # @service ParseWorker (解析线程)
│           └── chunk_worker.py      # @service ChunkWorker (分块+向量化线程)
├── tests/                           # 测试目录
└── doc/                             # 文档
```

---

## 2. 模块依赖关系

```
DBService  ←──────────────┐
    ↑                      │
    ├── AuthService  ──────┤
    ├── OSSClient    ──────┤  (独立, 无 deps)
    ├── LLMClient    ──────┤  (独立, 无 deps)
    ├── ParseWorker  ──────┤  deps=[DBService, OSSClient]
    ├── ChunkWorker  ──────┤  deps=[DBService, LLMClient]
    │                      │
    ├── KbService    ──────┤  deps=[DBService]
    ├── FileService  ──────┤  deps=[DBService, OSSClient]
    ├── ParseService ──────┤  deps=[DBService, ParseWorker, ChunkWorker]
    ├── SessionService ────┤  deps=[DBService]
    └── RAGService   ──────┘  deps=[DBService, LLMClient]
```

---

## 3. 数据库表

| 表名 | 说明 | 前缀 |
|------|------|------|
| `knowledge_bases` | 知识库 | kb_ |
| `kb_members` | 知识库成员 | - |
| `kb_nodes` | 文件/文件夹统一表 | nd_ |
| `kb_file_records` | 文件解析记录 | - |
| `parse_tasks` | 解析任务 | task_ |
| `kb_chunks` | 向量块 (pgvector) | chk_ |
| `sessions` | 会话 | sess_ |
| `messages` | 消息 | msg_ |

## 4. API 接口

### 4.1 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/knowledge-bases | 创建知识库 |
| GET | /api/v1/knowledge-bases | 我的知识库列表 |
| GET | /api/v1/knowledge-bases/{kb_id} | 详情 |
| PUT | /api/v1/knowledge-bases/{kb_id} | 更新 |
| DELETE | /api/v1/knowledge-bases/{kb_id} | 删除 |
| POST | /api/v1/knowledge-bases/{kb_id}/share-link | 生成分享链接 |
| GET | /api/v1/knowledge-bases/public | 公开知识库列表 |
| GET | /api/v1/knowledge-bases/shared/{share_token} | 分享链接查看 |
| POST | /api/v1/knowledge-bases/{kb_id}/join | 加入知识库 |

### 4.2 文件/文件夹

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/ | 上传/创建文件夹 |
| GET | /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/ | 列表 |
| GET | /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/{file_name}/detail | 文件详情 |
| DELETE | /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/{file_name} | 删除 |

### 4.3 解析任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks | 任务列表 |
| POST | /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/parsed | 查看解析文本 |
| PUT | /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/parsed | 修改解析文本 |
| POST | /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/chunk | 提交分块 |

### 4.4 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/sessions | 会话列表 |
| GET | /api/v1/sessions/{session_id}/messages | 历史消息 |
| DELETE | /api/v1/sessions/{session_id} | 删除会话 |

### 4.5 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /v1/chat/completions | OpenAI 兼容流式问答 |

### 4.6 空间统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/users/me/storage | 用户空间统计 |

---

## 5. 关键技术决策

### 5.1 认证方案

- 认证通过 `get_current_user` (FastAPI Depends) 实现
- AuthService 在 `@on_start` 时将自身注册到模块级单例
- Depends 函数从单例获取 AuthService 实例进行 token 验证
- 通过 `GET /v1/java-adapter/auth/current-user` 验证 JWT

### 5.2 异步任务 Worker

- ParseWorker / ChunkWorker 使用 `threading.Thread` + 独立 `asyncio event loop`
- 各持有独立 `Queue`，通过 `submit()` 接收任务
- `@on_end` 向 Queue 投入 `None` 哨兵值退出线程

### 5.3 状态机

```
upload → pending → processing → parsed → chunked
                        ↘ failed ↗
状态变更由 Worker 处理，状态校验在 Service 层
```

### 5.4 LangGraph 编排

- 图节点: retrieve → build_prompt → END
- 通过 `configurable` 传递运行时依赖 (chunk_repo, llm_client, node_repo)
- 支持流式 (SSE, text/event-stream) 和非流式两种模式

### 5.5 向量查询

- pgvector + cosine 距离排序
- 按 kb_ids / file_ids 范围筛选
- embedding 模型: qwen-embedding (1024 维)

---

## 6. 启动方式

```bash
# 安装依赖
uv sync

# 确保 PostgreSQL + pgvector 已部署并创建数据库
# 创建 pgvector 扩展: CREATE EXTENSION IF NOT EXISTS vector;

# 启动
uv run python main.py
# http://localhost:8000/health
```

---

## 7. 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| DATABASE_URL | PostgreSQL 连接串 | postgresql+asyncpg://... |
| OSS_ENDPOINT | OSS 端点 | - |
| OSS_ACCESS_KEY | OSS AccessKey | - |
| OSS_SECRET_KEY | OSS SecretKey | - |
| OSS_BUCKET | OSS Bucket | ly-ai-studio |
| OSS_BASE_URL | OSS 访问前缀 | - |
| JAVA_BASE_URL | Java 微服务地址 | - |
| LITELLM_API_BASE | litellm 网关地址 | - |
| LITELLM_API_KEY | litellm API Key | - |
| EMBEDDING_MODEL | Embedding 模型名 | qwen-embedding |
| LOG_LEVEL | 日志级别 | INFO |

---

## 8. 待完善事项

- [ ] 数据库迁移脚本 (init_db.py / Alembic)
- [ ] 单元测试 (pytest + pytest-asyncio)
- [ ] 文件解析多模态支持 (图片/音频/视频/OCR)
- [ ] 解析失败文件重试接口
- [ ] 知识库 public 公开端口
- [ ] 联网搜索工具
- [ ] 知识库文件移动操作
- [ ] 模型管理后台
