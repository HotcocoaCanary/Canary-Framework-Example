from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    id: str = Field(description="会话 ID")
    title: Optional[str] = Field(default=None, description="会话标题 (取第一条用户消息前 50 字符)")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class MessageResponse(BaseModel):
    role: str = Field(description="角色: user / assistant")
    content: str = Field(description="消息内容")
    sources: list[dict] = Field(default_factory=list, description="溯源信息")


class KnowledgeScope(BaseModel):
    knowledge_id: str = Field(description="知识库 ID")
    file_ids: list[str] = Field(default_factory=list, description="文件 ID 列表, 空数组表示整个知识库")


class ChatCompletionRequest(BaseModel):
    content: str = Field(description="用户问题")
    stream: bool = Field(default=True, description="是否流式返回")
    session_id: Optional[str] = Field(default=None, description="会话 ID, null 则自动创建新会话")
    knowledge_scope: list[KnowledgeScope] = Field(default_factory=list,
                                                  description="检索范围, 空数组表示用户所有知识库")
