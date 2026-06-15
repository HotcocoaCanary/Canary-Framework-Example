from canary_framework import service
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase

from app.common.response import R, PageR
from app.module.file.schema import FileResponse, CreateFileRequest, PatchFileRequest
from app.module.file.service import FileService


@service()
class FileRouter(ServiceBase):
    router = Router(prefix='/file', tags=["file"])
    file_service: FileService

    @router.post(
        '/{kb_id}/{folder_path:path}',
        summary="上传文件/创建文件夹",
        description="在指定路径创建文件或文件夹，若父目录不存在则自动创建",
        request_model=CreateFileRequest,
        response_model=R[dict],
    )
    async def create(self, kb_id: str, folder_path: str, body: CreateFileRequest):
        success, result = self.file_service.create(kb_id, folder_path, body)
        return R.ok(result) if success else R.fail(result)

    @router.get(
        '/{kb_id}/{folder_path:path}?page={page}&size={size}',
        summary="文件列表",
        description="获取指定路径下的所有文件和文件夹",
        response_model=PageR[FileResponse],
    )
    async def list_nodes(self, kb_id: str, folder_path: str, page: int = 1, size: int = 20):
        success, result = self.file_service.list_nodes(kb_id, folder_path, page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @router.delete(
        '/{kb_id}/{folder_path:path}',
        summary="删除文件/文件夹",
        response_model=R[str],
    )
    async def delete_by_path(self, kb_id: str, folder_path: str):
        success, result = self.file_service.delete_by_path(kb_id, folder_path)
        return R.ok(result) if success else R.fail(result)

    @router.patch(
        '/{kb_id}/{folder_path:path}',
        summary="修改文件信息",
        request_model=PatchFileRequest,
        response_model=R[dict],
    )
    async def update_by_path(self, kb_id: str, folder_path: str, body: PatchFileRequest):
        success, result = self.file_service.update_by_path(kb_id, folder_path, body)
        return R.ok(result) if success else R.fail(result)
