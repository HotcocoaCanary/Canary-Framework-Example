from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateKbRequest(BaseModel):
    name: str = Field(max_length=200, description="知识库名称")
    description: Optional[str] = Field(default=None, description="描述")
    permission: str = Field(default="private", description="权限: private / shared")


class KbResponse(BaseModel):
    id: str = Field(description="知识库 ID")
    name: str = Field(description="知识库名称")
    description: Optional[str] = Field(default=None, description="描述")
    permission: str = Field(description="权限")
    share_token: Optional[str] = Field(default=None, description="分享 token")
    created_by: str = Field(description="创建者")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    file_count: int = Field(default=0, description="文件数量")
    total_size: int = Field(default=0, description="总大小 (bytes)")

class UpdateKbRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200, description="知识库名称")
    description: Optional[str] = Field(default=None, description="描述")
    permission: Optional[str] = Field(default=None, description="权限: private / shared")