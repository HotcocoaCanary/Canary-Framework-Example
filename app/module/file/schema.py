from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class FileResponse(BaseModel):
    file_id: str = Field(description="文件 ID")
    name: str = Field(description="文件/文件夹名称")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    file_size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="处理状态")
    updated_at: datetime = Field(description="更新时间")


class FileDetailResponse(BaseModel):
    file_id: str = Field(description="文件 ID")
    name: str = Field(description="文件名称")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    file_size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="处理状态")
    oss_url: Optional[str] = Field(default=None, description="文件存储地址")
    chunk_count: int = Field(default=0, description="分块数量")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class CreateFolderRequest(BaseModel):
    name: str = Field(description="文件夹名称")


class UploadFileResponse(BaseModel):
    file_id: str = Field(description="文件 ID")
    name: str = Field(description="文件名称")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    file_size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="处理状态")
