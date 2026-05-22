from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateKbRequest(BaseModel):
    name: str = Field(max_length=200, description="知识库名称")
    description: Optional[str] = Field(default=None, description="描述")
    permission: str = Field(default="private", description="权限: private / shared")


class UpdateKbRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200, description="知识库名称")
    description: Optional[str] = Field(default=None, description="描述")
    permission: Optional[str] = Field(default=None, description="权限: private / shared")


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


class ShareLinkResponse(BaseModel):
    share_url: str = Field(description="分享链接 URL")


class CreateFolderRequest(BaseModel):
    name: str = Field(description="文件夹名称")


class FileItemResponse(BaseModel):
    id: str = Field(description="文件/文件夹 ID")
    name: str = Field(description="名称")
    node_type: Optional[str] = Field(default=None, description="节点类型: null=文件夹, 扩展名=文件")
    size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="解析状态: pending/processing/parsed/chunked/failed")
    updated_at: datetime = Field(description="更新时间")


class FileDetailResponse(BaseModel):
    id: str = Field(description="文件 ID")
    name: str = Field(description="文件名")
    node_type: Optional[str] = Field(default=None, description="文件类型 (扩展名)")
    size: Optional[int] = Field(default=None, description="文件大小 (bytes)")
    status: Optional[str] = Field(default=None, description="解析状态")
    oss_url: Optional[str] = Field(default=None, description="OSS 访问 URL")
    chunk_count: int = Field(default=0, description="已分块数量")
    parse_task_id: Optional[str] = Field(default=None, description="所属解析任务 ID")
    updated_at: datetime = Field(description="更新时间")


class ParseTaskFileItem(BaseModel):
    file_id: str = Field(description="文件 ID")
    file_name: str = Field(description="文件名")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    status: str = Field(description="解析状态")
    error_msg: Optional[str] = Field(default=None, description="错误信息")


class ParseTaskResponse(BaseModel):
    parse_task_id: str = Field(description="解析任务 ID")
    file_list: list[ParseTaskFileItem] = Field(description="文件列表")
    created_at: datetime = Field(description="创建时间")


class ParsedFileResponse(BaseModel):
    file_id: str = Field(description="文件 ID")
    file_name: str = Field(description="文件名")
    file_type: Optional[str] = Field(default=None, description="文件类型")
    parsed_text: Optional[str] = Field(default=None, description="解析后的全量文本")
    status: str = Field(description="状态")
    updated_at: datetime = Field(description="更新时间")


class ViewParsedRequest(BaseModel):
    file_ids: list[str] = Field(description="要查看的文件 ID 列表")


class UpdateParsedFileItem(BaseModel):
    file_id: str = Field(description="文件 ID")
    parsed_text: str = Field(description="修改后的解析文本")


class UpdateParsedRequest(BaseModel):
    files: list[UpdateParsedFileItem] = Field(description="要更新的文件列表")


class ChunkRequest(BaseModel):
    file_ids: list[str] = Field(description="要提交分块的文件 ID 列表")


class ChunkedFileItem(BaseModel):
    file_id: str = Field(description="文件 ID")
    chunk: list[dict] = Field(description="分块数据")
    status: str = Field(description="分块状态")


class ChunkResultResponse(BaseModel):
    task_id: str = Field(description="解析任务 ID")
    chunked_files: list[ChunkedFileItem] = Field(description="分块文件列表")
