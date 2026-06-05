from canary_framework import router, get, post, delete
from canary_framework.core.router import RouterBase

from app.common.response import R, PageR
from app.module.file.schema import FileResponse, FileDetailResponse, CreateFolderRequest
from app.module.file.service import FileService


@router(prefix='/file', tags=["file"])
class FileRouter(RouterBase):
    file_service: FileService

    @post(
        '/{kb_id}/folder/{folder_path:path}',
        summary="创建文件夹",
        request_model=CreateFolderRequest,
        response_model=R[dict],
    )
    async def create_folder(self, kb_id: str, folder_path: str, body: CreateFolderRequest):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"

        success, result = self.file_service.create_folder(kb_id, folder_path, body.name)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/{kb_id}/list/{folder_path:path}',
        summary="文件/文件夹列表",
        response_model=PageR[FileResponse],
    )
    async def list_nodes(self, kb_id: str, folder_path: str, page: int = 1, size: int = 20):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"

        success, result = self.file_service.list_nodes(kb_id, folder_path, page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/{kb_id}/detail/{folder_path:path}/{file_name}',
        summary="文件详情",
        response_model=R[FileDetailResponse],
    )
    async def get_file_detail(self, kb_id: str, folder_path: str, file_name: str):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"

        success, result = self.file_service.get_file_detail(kb_id, folder_path, file_name)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/{kb_id}/delete/{folder_path:path}/{file_name}',
        summary="删除文件/文件夹",
        response_model=R[str],
    )
    async def delete_node(self, kb_id: str, folder_path: str, file_name: str):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"

        success, result = self.file_service.delete_node(kb_id, folder_path, file_name)
        return R.ok(result) if success else R.fail(result)
