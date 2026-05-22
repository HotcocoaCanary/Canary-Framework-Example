# ly-ai-studio 需求文档 v0.2

## 1. 项目概述

基于 CF + LangChain/LangGraph 的 Agent 工作平台。首期目标：知识库 + RAG 问答。

---

## 2. 用户体系

- 对接现有 Java 微服务（PigX 体系）
- CF 侧不存储用户密码，不维护用户表
- 鉴权流程：
  1. 前端携带 JWT (Authorization header)
  2. CF 中间件提取 token，透传到 Java 服务
  3. 调用 `GET /v1/java-adapter/auth/current-user` 验证身份，获取 UserContext
  4. UserContext 包含: user_id, username, tenant_id, roles 等

---

## 3. 知识库

### 3.1 内容类型

| 类型 | 处理方式 | 工具 |
|------|---------|------|
| PDF / Word / TXT / Markdown | 提取文本 | markitdown |
| Excel / PPT | 提取文本 | markitdown |
| 图片 (jpg/png/...) | 多模态 -- 描述性文本 | qwen-vl |
| 音频 (mp3/wav/...) | ASR -- 文本 | qwenasr |
| 视频 (mp4/...) | 抽帧 + 多模态 + ASR -- 文本 | qwen-vl + qwenasr |
| URL | 网页内容 -- Markdown | markitdown |
| OCR 图片/文档 | OCR -- 文本 | qwenocr |

所有类型最终统一为文本后分块。

### 3.2 权限模型

| 权限 | 可见性 | 加入方式 | 编辑权限 |
|------|--------|----------|----------|
| 私有 | 仅创建者 | -- | 创建者 |
| 分享可见 | 任何人（有链接） | 点击链接 -- 加入 | 创建者 |
| 公开 | 所有人 | 浏览 -- 加入 | 创建者 |

- 分享链接不限定具体用户，任何人拿到链接即可查看并加入
- 只有创建者可编辑/删除知识库内容

### 3.3 目录结构

- 知识库内支持文件夹层级
- 文件存储到文件夹中
- RAG 检索范围可按文件夹/文件筛选

### 3.4 空间统计

- 统计用户作为创建者的所有知识库文件大小
- 文件存 OSS，数据库记录文件大小

---

## 4. 文档处理流程

```
文件上传 -- OSS 存储
         -- 类型识别 -- 对应处理工具 -- 文本
         -- 分块
              chunk_size = 512 tokens
              overlap = 64 tokens
         -- 向量化 (qwen-embedding)
         -- 存入 pgvector
```

### 4.1 存储

- 使用 PostgreSQL + pgvector
- 两个核心接口：store(chunks, embedding)、search(embedding, top_k)
- 关系表存：文件元信息（名称、大小、类型、OSS URL、文件夹路径）

---

## 5. 会话管理

- 会话 CRUD：创建/切换/删除/列表
- 持久化到 PostgreSQL
- 每条消息记录 role (user/assistant) 和 content
- 每轮问答引用当前会话的历史上下文（短期记忆）

## 6. RAG 问答

### 6.1 检索范围

- 默认：用户所有已加入的知识库
- 可选：用户指定文件/文件夹/知识库范围

### 6.2 答案溯源

- 文件级溯源：引用文件名 + OSS 预览链接

### 6.3 流式返回

- SSE (Server-Sent Events)
- OpenAI Chat Completion 协议规范
- 接口: POST /v1/chat/completions

### 6.4 编排引擎

- LangGraph 编排
- 图节点：检索 -- prompt 构建 -- LLM 调用 -- 答案 + 溯源返回
- 注入会话上下文（短期记忆）

---

## 7. 模型调用

- litellm 统一调用
- 模型配置：环境变量管理（本期不做管理后台）
- 不支持多模型切换

### 7.1 模型选型

| 用途 | 模型 |
|------|------|
| Embedding | qwen-embedding |
| LLM (问答) | 通过 litellm 配置 |
| 多模态 | qwen-vl |
| ASR | qwenasr |
| OCR | qwenocr |

---

## 8. 工具调用

- 本期仅联网搜索工具
- 预留 Tool 基类

---

## 9. 接口规范

| 模块 | 协议 | 说明 |
|------|------|------|
| 知识库 CRUD | REST | 创建/删除/修改/列表/详情 |
| 文件夹管理 | REST | 新建/删除/移动 |
| 文件上传/删除 | REST | 上传到 OSS，异步处理 |
| 会话管理 | REST | CRUD |
| RAG 问答 | REST + SSE | OpenAI 兼容流式 |
| 知识库浏览/加入 | REST | 公开 KB 列表 + 加入 |

---

## 10. 技术依赖

| 组件 | 选型 |
|------|------|
| 框架 | CF (Canary Framework) |
| Web 层 | cf.web.fastapi |
| LLM 编排 | LangGraph |
| 向量数据库 | PostgreSQL + pgvector |
| 对象存储 | OSS (S3 兼容) |
| 文档解析 | markitdown |
| OCR | qwenocr |
| ASR | qwenasr |
| 多模态 | qwen-vl |
| Embedding | qwen-embedding |
| 模型网关 | litellm |
