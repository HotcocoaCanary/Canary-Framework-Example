# API 接口设计

## 目录

- [1. 通用约定](#1-通用约定)
- [2. 知识库](#2-知识库)
- [3. 文件/文件夹 CRUD](#3-文件文件夹-crud)
- [4. 解析任务](#4-解析任务)
- [5. 会话](#5-会话)
- [6. 问答](#6-问答)
- [7. 空间统计](#7-空间统计)
- [附录: 错误码](#附录-错误码)

---

## 1. 通用约定

### 1.1 认证

所有接口需要 `Authorization: Bearer <jwt>` header。JWT 由 Java 微服务签发，CF 侧透传验证。

### 1.2 响应格式

```json
{
  "code": 0,
  "data": {
    ...
  },
  "msg": "ok"
}
```

| 字段   | 说明              |
|------|-----------------|
| code | 0 = 成功, 1 = 失败  |
| data | 响应数据, 失败时为 null |
| msg  | 消息, 失败时为错误描述    |

### 1.3 分页格式（对齐 MyBatis Plus IPage）

```json
{
  "code": 0,
  "data": {
    "records": [
      ...
    ],
    "total": 100,
    "size": 20,
    "current": 1,
    "pages": 5
  },
  "msg": "ok"
}
```

| 字段      | 类型    | 说明             |
|---------|-------|----------------|
| records | array | 当前页数据          |
| total   | int   | 总记录数           |
| size    | int   | 每页大小           |
| current | int   | 当前页码 (1-based) |
| pages   | int   | 总页数            |

### 1.4 路径前缀

所有业务 API 以 `/api/v1` 开头。问答 API 为 `/v1/chat/completions`（OpenAI 兼容）。

---

## 2. 知识库

### 2.1 创建

```
POST /api/v1/knowledge-bases
```

**Request:**

```json
{
  "name": "我的知识库",
  "description": "",
  "permission": "private"
}
```

| 字段          | 必填 | 说明                       |
|-------------|----|--------------------------|
| name        | 是  | 知识库名称, max 200           |
| description | 否  | 描述                       |
| permission  | 否  | `private`(默认) / `shared` |

**Response:** `R[KbResponse]`

```json
{
  "code": 0,
  "data": {
    "id": "kb_xxx",
    "name": "我的知识库",
    "description": "",
    "permission": "private",
    "share_token": null,
    "created_by": "user_001",
    "created_at": "2026-05-19T10:00:00Z",
    "updated_at": "2026-05-19T10:00:00Z",
    "file_count": 0,
    "total_size": 0
  },
  "msg": "ok"
}
```

### 2.2 我的知识库列表

```
GET /api/v1/knowledge-bases?current=1&size=20
```

返回当前用户创建或加入的所有知识库。

**Response:** `P[R[KbResponse]]`

### 2.3 详情

```
GET /api/v1/knowledge-bases/{kb_id}
```

**Response:** `R[KbResponse]`

### 2.4 更新

```
PUT /api/v1/knowledge-bases/{kb_id}
```

**Request:**

```json
{
  "name": "...",
  "description": "...",
  "permission": "shared"
}
```

**约束:** permission 仅允许 `private` / `shared`，不允许设置为 `public`, public属性是为后续预留的，要公开成为public需要走另外的端口，但是现在先不实现。

### 2.5 删除

```
DELETE /api/v1/knowledge-bases/{kb_id}
```

仅创建者可操作。删除级联移除所有文件、文件夹、chunks 和成员记录。

### 2.6 分享链接

```
POST /api/v1/knowledge-bases/{kb_id}/share-link
```

- 仅 `shared` 权限的 KB 且创建者可操作
- 生成/刷新 `share_token`，返回分享 URL

**Response:** `R[{ share_url: "https://..." }]`

### 2.7 公开知识库列表

```
GET /api/v1/knowledge-bases/public?current=1&size=20&keyword=xxx
```

无需加入即可浏览的公开 KB。

### 2.8 分享链接查看

```
GET /api/v1/knowledge-bases/shared/{share_token}
```

- 根据 share_token 查看 KB 信息。
- public知识库和shared知识库都会有访问url

### 2.9 加入

```
POST /api/v1/knowledge-bases/{kb_id}/join
```

- 公开知识库和分享可见知识库都需要通过链接访问后，请求这个接口来加入，但是这是前端的逻辑，我们只需要处理发送这个请求的时候，拿到kb_id和token对应的用户，然后关联即可
- 加入后出现在"我的知识库列表"中，角色为 `member`
- 已加入则幂等返回

---

## 3. 文件/文件夹 CRUD

路径即地址。末尾带 `/` 表示目录操作，不带 `/` 且带扩展名为文件操作。
同一知识库下出现同名文件夹或者同名文件的话自动在后面加上符号 `_{编号，从1开始}`，避免出现问题

### 3.1 上传

```
POST /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/
```

两种 Content-Type 区分：

- multipart/form-data + files → 上传文件
- application/json + {"name": "新文件夹"} → 创建空文件夹

**Request:**

- `multipart/form-data`+files
- `application/json` + `{"name": "新文件夹"}`

| 字段    | 类型     | 说明                                         |
|-------|--------|--------------------------------------------|
| files | file[] | 可包含相对路径 (如 `docs/a.pdf`, `docs/sub/b.txt`) |

**行为:**

- 文件名不含 `/` → 存入当前 folder_path
- 文件名含 `/` → 自动创建中间文件夹, 文件存入对应位置
- 所有文件作为一个解析任务批次
- 解析失败的文件后续需要提供重新解析接口，但本次开发不考虑

**Response:** `R[ParseTaskResponse]`

### 3.2 列表

```
GET /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/?current=1&size=20
```

**Response:** `P[R[FileItemResponse]]`

```json
{
  "records": [
    {
      "id": "nd_xxx",
      "name": "产品手册.pdf",
      "node_type": "pdf",
      "size": 2048000,
      "status": "parsed",
      "updated_at": "2026-05-19T10:00:00Z"
    },
    {
      "id": "nd_yyy",
      "name": "math",
      "node_type": null,
      "size": null,
      "status": null,
      "updated_at": "2026-05-19T10:00:00Z"
    }
  ],
  "total": 2,
  "size": 20,
  "current": 1,
  "pages": 1
}
```

- `node_type`: `null` = 文件夹, 文件时为扩展名
- `status`: 仅文件有值 (pending/processing/parsed/chunked/failed)

### 3.3 文件详情

```
GET /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/{file_name}/detail
```

**Response:** `R[FileItemResponse]`

```json
{
  "id": "nd_xxx",
  "name": "产品手册.pdf",
  "node_type": "pdf",
  "size": 2048000,
  "status": "parsed",
  "oss_url": "",
  "chunk": [
    //解析之后的文件才有
    {}
  ],
  "parse_task_id": "",
  "updated_at": "2026-05-19T10:00:00Z"
}
```

额外返回 `oss_url`, `chunk_count`, `parse_task_id`。

### 3.4 删除

```
DELETE /api/v1/knowledge-bases/file-op/{kb_id}/{folder_path}/{file_name}
```

文件夹递归删除内部所有文件和子文件夹。

---

## 4. 解析任务

### 4.1 任务列表

```
GET /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks?current=1&size=20
```

**Response:** `P[R[ParseTaskResponse]]`

```json
{
  "records": [
    {
      "parse_task_id": "task_xxx",
      "file_list": [
        {
          "file_id": "nd_001",
          "file_name": "产品手册.pdf",
          "file_type": "pdf",
          "status": "parsed",
          "error_msg": null
        },
        {
          "file_id": "nd_002",
          "file_name": "架构图.png",
          "file_type": "png",
          "status": "processing",
          "error_msg": null
        }
      ],
      "created_at": "2026-05-19T10:00:00Z"
    }
  ],
  "total": 1,
  "size": 20,
  "current": 1,
  "pages": 1
}
```

### 4.2 查看解析文本

```
POST /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/parsed
```

**Request:**

```json
{
  "file_ids": [
    "nd_001",
    "nd_002"
  ]
}
```

**Response:** `R[list[ParsedFileResponse]]`

```json
{
  "code": 0,
  "data": [
    {
      "file_id": "nd_001",
      "file_name": "产品手册.pdf",
      "file_type": "pdf",
      "parsed_text": "全文解析结果...",
      "status": "parsed",
      "updated_at": "2026-05-19T10:00:00Z"
    }
  ],
  "msg": "ok"
}
```

### 4.3 修改解析文本

```
PUT /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/parsed
```

**Request:**

```json
{
  "files": [
    {
      "file_id": "nd_001",
      "parsed_text": "修改后的文本"
    }
  ]
}
```

**约束:** 仅 `parsed` 状态的文件可修改。
**Response:** 返回更新后的 `R[list[ParsedFileResponse]]`

### 4.4 提交分块

```
POST /api/v1/knowledge-bases/file-op/{kb_id}/parse-tasks/{task_id}/chunk
```

**Request:**

```json
{
  "file_ids": [
    "nd_001"
  ]
}
```

**约束:** 仅 `parsed` 状态的文件可提交。提交后进入后台队列执行分块+embedding+入库。

**Response:** `R[ChunkResultResponse]`

```json
{
  "code": 0,
  "data": {
    "task_id": "task_xxx",
    "chunked_files": [
      {
        "file_id": "nd_001",
        "chunk": [
          {}
        ],
        "status": "completed"
      },
      {
        "file_id": "nd_002",
        "chunk": [
          {}
        ],
        "status": "pending"
      }
    ]
  },
  "msg": "ok"
}
```

---

## 5. 会话

### 5.1 列表

```
GET /api/v1/sessions?current=1&size=20
```

**Response:** `P[R[SessionResponse]]`

```json
{
  "records": [
    {
      "id": "sess_xxx",
      "title": "产品支持哪些部署方式？",
      "created_at": "2026-05-19T10:00:00Z",
      "updated_at": "2026-05-19T10:05:00Z"
    }
  ]
}
```

标题自动取第一条用户消息的前 50 个字符。

### 5.2 历史消息

```
GET /api/v1/sessions/{session_id}/messages?current=1&size=50
```

**Response:** `P[R[MessageResponse]]`

```json
{
  "records": [
    {
      "role": "user",
      "content": "",
      "sources": []
    },
    {
      "role": "assistant",
      "content": "",
      "sources": []
    }
  ]
}
```

### 5.3 删除

```
DELETE /api/v1/sessions/{session_id}
```

---

## 6. 问答

```
POST /v1/chat/completions
```

OpenAI Chat Completion 协议兼容。

**Request:**

```json
{
  "content": "产品支持哪些部署方式？",
  "stream": true,
  "session_id": null,
  "knowledge_scope": [
    {
      "knowledge_id": "kb_abc",
      "file_ids": [
        "nd_001"
      ]
    },
    {
      "knowledge_id": "kb_xyz",
      "file_ids": []
    }
  ]
}
```

| 字段              | 必填 | 说明                                         |
|-----------------|----|--------------------------------------------|
| content         | 是  | 本次问题                                       |
| stream          | 否  | 默认 true                                    |
| session_id      | 否  | null → 自动创建新会话，并推送session事件给前端             |
| knowledge_scope | 否  | 为空或者不传表示用户所有 KB; `file_ids` 为 `[]` 表示整个 KB |

**Response:** SSE 流式, `text/event-stream`

```
event: session
data: {"session_id":"sess_xxx"}

event: message
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"产品"},"index":0}]}

event: message
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop","index":0}],"sources":[...]}

data: [DONE]
```

溯源字段 `sources`:

| 字段          | 类型           | 说明                                     |
|-------------|--------------|----------------------------------------|
| file_name   | str          | 文件名                                    |
| file_type   | str          | 扩展名                                    |
| oss_url     | str          | OSS 访问地址                               |
| chunk_index | int          | 块序号                                    |
| content     | str          | 匹配到的文本片段                               |
| page        | int\|null    | 页码 (PDF/Word/PPT); 音视频/图片/Excel 为 null |
| position    | number\|null | 时间戳 (音视频); 其他为 null                    |

---

## 7. 空间统计

```
GET /api/v1/users/me/storage
```

**Response:** `R[StorageResponse]`

```json
{
  "code": 0,
  "data": {
    "used_bytes": 104857600,
    "used_formatted": "100 MB"
  },
  "msg": "ok"
}
```

仅统计用户作为创建者的知识库文件大小。

---

## 附录: 错误码

| code | msg    | 说明          |
|------|--------|-------------|
| 0    | ok     | 成功          |
| 1    | {具体错误} | 通用业务错误      |
| 401  | 未登录    | JWT 无效或过期   |
| 403  | 无权限    | 非创建者试图编辑    |
| 404  | 资源不存在  | KB/文件/会话不存在 |
| 409  | 状态冲突   | 状态机不允许的操作   |
| 413  | 文件过大   | 超出大小限制      |
| 500  | 服务器错误  | 内部异常        |

### 状态冲突 (409) 场景

| 场景                           | msg                                   |
|------------------------------|---------------------------------------|
| 对 processing 状态的文件提交分块       | `文件 nd_xxx 状态为 processing，需要先解析再提交分块` |
| 修改 chunked 状态文件的 parsed_text | `文件 nd_xxx 状态为 chunked，不允许修改解析文本`     |
| 对 pending 状态的文件提交分块          | `文件 nd_xxx 状态为 pending，需要先解析再提交分块`    |
