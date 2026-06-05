from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FileResponse(BaseModel):
    file_id: str = Field(description="文件 ID")
    name: str = Field(description="文件/文件夹名称")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    file_size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="处理状态")
    updated_at: datetime = Field(description="更新时间")


class CreateFileRequest(BaseModel):
    file_type: Optional[str] = Field(default=None, description="文件类型，None 表示文件夹")


class PatchFileRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="新名称")
    status: Optional[str] = Field(default=None, description="处理状态")
