from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubmitUrlRequest(BaseModel):
    url: str = Field(description="要采集的 URL")


class CollectionItemResponse(BaseModel):
    id: str = Field(description="采集项 ID")
    url: str = Field(description="采集 URL")
    title: Optional[str] = Field(default=None, description="标题")
    content: Optional[str] = Field(default=None, description="内容")
    status: str = Field(default="pending", description="状态: pending, success, failed")
    is_imported: bool = Field(default=False, description="是否已导入知识库")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ImportToKbRequest(BaseModel):
    kb_id: str = Field(description="目标知识库 ID")


class ImportToKbResponse(BaseModel):
    file_id: str = Field(description="导入后的文件 ID")
    name: str = Field(description="文件名")
    status: str = Field(description="文件状态")
