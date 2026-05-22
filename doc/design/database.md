# 数据库设计

## 目录

- [1. ORM 选型](#1-orm-选型)
- [2. 表结构](#2-表结构)
- [3. OSS 路径](#3-oss-路径)
- [4. ID 生成](#4-id-生成)
- [5. 状态机](#5-状态机)
- [6. 索引策略](#6-索引策略)

---

## 1. ORM 选型

**SQLModel** = SQLAlchemy 异步引擎 + Pydantic 模型。

- 类型安全，完美配合 FastAPI
- 异步支持 (`sqlalchemy.ext.asyncio`)
- 内置分页 (`limit/offset`)
- 数据库: PostgreSQL 15+ + pgvector 扩展

---

## 2. 表结构

### 2.1 knowledge_bases

| 列           | 类型             | 说明                              |
|-------------|----------------|---------------------------------|
| id          | VARCHAR(32) PK | `kb_` + nanoid                  |
| name        | VARCHAR(200)   | 知识库名                            |
| description | TEXT           | 描述                              |
| permission  | VARCHAR(10)    | `private` / `shared` / `public` |
| share_token | VARCHAR(64)    | 分享 token, shared 时生成            |
| created_by  | VARCHAR(64)    | 创建者 user_id                     |
| created_at  | TIMESTAMP      |                                 |
| updated_at  | TIMESTAMP      |                                 |

### 2.2 kb_members

| 列         | 类型                | 说明                 |
|-----------|-------------------|--------------------|
| kb_id     | VARCHAR(32) PK,FK |                    |
| user_id   | VARCHAR(64) PK    |                    |
| role      | VARCHAR(10)       | `owner` / `member` |
| joined_at | TIMESTAMP         |                    |

### 2.3 kb_nodes（文件 + 文件夹统一表）

| 列           | 类型                 | 说明                                     |
|-------------|--------------------|----------------------------------------|
| id          | VARCHAR(32) PK     | `nd_` + nanoid                         |
| kb_id       | VARCHAR(32) FK     |                                        |
| name        | VARCHAR(500)       | 文件名或文件夹名                               |
| node_type   | VARCHAR(20) NULL   | `NULL`=文件夹; 有值=文件扩展名                   |
| size        | BIGINT NULL        | 文件字节数, 文件夹 NULL (仅文件)                  |
| parent_path | VARCHAR(1000)      | 直接父目录路径，根目录节点为 null                    |
| full_path   | VARCHAR(1000)      | `"/"` / `"/math"` / `"/math/产品手册.pdf"` |
| oss_key     | VARCHAR(1000) NULL | OSS 路径 (仅文件)                           |
| oss_url     | VARCHAR(2000) NULL | OSS 访问 URL (仅文件)                       |
| created_by  | VARCHAR(64)        |                                        |
| created_at  | TIMESTAMP          |                                        |
| updated_at  | TIMESTAMP          |                                        |

**查询规则:**

- 文件夹列表: `WHERE node_type IS NULL`
- 文件列表: `WHERE node_type IS NOT NULL`
- 子节点: `WHERE kb_id = :kb_id AND parent_path = '/math'`
- 根目录： `WHERE kb_id = :kb_id AND parent_path IS NULL`

### 2.4 kb_file_records（文件解析记录表）

| 列             | 类型                  | 说明                                                 |
|---------------|---------------------|----------------------------------------------------|
| file_id       | VARCHAR(32) PK,FK   | 关联 kb_nodes.id                                     |
| status        | VARCHAR(20)         | `pending`/`processing`/`parsed`/`chunked`/`failed` |
| parsed_text   | TEXT NULL           | 解析后的全量文本                                           |
| error_msg     | TEXT NULL           | 失败原因                                               |
| parse_task_id | VARCHAR(32) FK NULL | 所属解析任务                                             |
| created_at    | TIMESTAMP           |                                                    |
| updated_at    | TIMESTAMP           |                                                    |

### 2.5 parse_tasks

| 列          | 类型             | 说明                 |
|------------|----------------|--------------------|
| id         | VARCHAR(32) PK | `task_` + nanoid   |
| kb_id      | VARCHAR(32) FK |                    |
| created_by | VARCHAR(64)    |                    |
| created_at | TIMESTAMP      |                    |
| updated_at | TIMESTAMP      |                    |

与文件的关联通过 `kb_file_records.parse_task_id` 反向查询。

### 2.6 kb_chunks

| 列           | 类型             | 说明                         |
|-------------|----------------|----------------------------|
| id          | VARCHAR(32) PK | `chk_` + nanoid            |
| file_id     | VARCHAR(32) FK | 关联 kb_nodes.id             |
| kb_id       | VARCHAR(32) FK |                            |
| content     | TEXT           | 文本片段                       |
| embedding   | vector(1024)   | qwen-embedding 向量          |
| chunk_index | INT            | 块序号                        |
| page        | INT NULL       | 页码 (PDF/Word/PPT)，音视频此字段为空 |
| created_at  | TIMESTAMP      |                            |

### 2.7 sessions

| 列          | 类型             | 说明               |
|------------|----------------|------------------|
| id         | VARCHAR(32) PK | `sess_` + nanoid |
| user_id    | VARCHAR(64)    |                  |
| name       | VARCHAR(200)   | 第一条用户消息          |
| created_at | TIMESTAMP      |                  |
| updated_at | TIMESTAMP      |                  |

### 2.8 messages

| 列          | 类型             | 说明                   |
|------------|----------------|----------------------|
| id         | VARCHAR(32) PK | `msg_` + nanoid      |
| session_id | VARCHAR(32) FK |                      |
| role       | VARCHAR(10)    | `user` / `assistant` |
| content    | TEXT           |                      |
| sources    | JSONB          | 溯源信息数组               |
| created_at | TIMESTAMP      |                      |

---

## 3. OSS 路径

```
ai/knowledge-base/{user_id}_{user_name}/{kb_id}/{full_path}
```

| 示例                                                         | 说明        |
|------------------------------------------------------------|-----------|
| `ai/knowledge-base/user_001_zhangsan/kb_abc/产品手册.pdf`      | 根目录文件     |
| `ai/knowledge-base/user_001_zhangsan/kb_abc/math/数学公式.pdf` | math 文件夹下 |

`full_path` 以 `/` 开头，OSS 路径中去除首 `/` 拼接。

---

## 4. ID 生成

统一使用 nanoid (21 字符) + 前缀：

| 前缀      | 实体          |
|---------|-------------|
| `kb_`   | 知识库         |
| `nd_`   | 节点 (文件/文件夹) |
| `task_` | 解析任务        |
| `chk_`  | 向量块         |
| `sess_` | 会话          |
| `msg_`  | 消息          |

---

## 5. 状态机

```
upload → pending → processing → parsed → chunked
                        ↘ failed ↗
```

**转换规则:**

| 当前状态       | 允许操作 | 目标状态        | 触发            |
|------------|------|-------------|---------------|
| pending    | 开始解析 | processing  | Worker        |
| processing | 解析完成 | parsed      | Worker        |
| processing | 解析失败 | failed      | Worker        |
| parsed     | 修改文本 | parsed (停留) | 用户 PUT        |
| parsed     | 提交分块 | chunked     | 用户 POST chunk |
| failed     | 重试   | processing  | Worker        |

**入口校验:**

| 接口              | 允许的状态               |
|-----------------|---------------------|
| PUT parsed_text | `parsed`            |
| POST chunk      | `parsed`            |
| Worker 解析       | `pending`, `failed` |

---

## 6. 索引策略

```sql
-- knowledge_bases
CREATE INDEX idx_kb_created_by ON knowledge_bases (created_by);
CREATE INDEX idx_kb_share_token ON knowledge_bases (share_token) WHERE share_token IS NOT NULL;

-- kb_members
CREATE UNIQUE INDEX idx_kbm_kb_user ON kb_members (kb_id, user_id);
CREATE INDEX idx_kbm_user_id ON kb_members (user_id);

-- kb_nodes
CREATE INDEX idx_node_parent ON kb_nodes (kb_id, parent_path);
CREATE INDEX idx_node_kb_path ON kb_nodes (kb_id, full_path);
CREATE INDEX idx_node_kb_type ON kb_nodes (kb_id, node_type);

-- kb_file_records
CREATE INDEX idx_record_task ON kb_file_records (parse_task_id);
CREATE INDEX idx_record_status ON kb_file_records (status);

-- kb_chunks (pgvector)
CREATE INDEX idx_chunk_embedding ON kb_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunk_file ON kb_chunks (file_id);
CREATE INDEX idx_chunk_kb ON kb_chunks (kb_id);

-- sessions
CREATE INDEX idx_session_user ON sessions (user_id);

-- messages
CREATE INDEX idx_msg_session ON messages (session_id);
CREATE INDEX idx_msg_created ON messages (session_id, created_at);
```
