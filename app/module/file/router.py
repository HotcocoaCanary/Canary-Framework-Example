from canary_framework import post, get, delete
from canary_framework.decorators import router

from app.module.file.schema import FileResponse, FileDetailResponse, CreateFolderRequest, UploadFileResponse
from app.common.response import R, PageR
from app.module.file.service import FileService


@router(prefix='/file', tags=["file"])
class FileRouter:
    file_service: FileService

    @post(
        path='/{kb_id}/folder/{folder_path:path}',
        summary="创建文件夹",
        request_model=CreateFolderRequest,
        response_model=R[dict],
        responses={
            "200": {"model": R[dict]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def create_folder(self, kb_id: str, folder_path: str, request: CreateFolderRequest):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"
        
        success, result = self.file_service.create_folder(kb_id, folder_path, request.name)
        return R.ok(result) if success else R.fail(result)

    @get(
        path='/{kb_id}/list/{folder_path:path}',
        summary="文件/文件夹列表",
        response_model=PageR[FileResponse],
        responses={
            "200": {"model": PageR[FileResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def list_nodes(self, kb_id: str, folder_path: str, page: int = 1, size: int = 20):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"
        
        success, result = self.file_service.list_nodes(kb_id, folder_path, page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @get(
        path='/{kb_id}/detail/{folder_path:path}/{file_name}',
        summary="文件详情",
        response_model=R[FileDetailResponse],
        responses={
            "200": {"model": R[FileDetailResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def get_file_detail(self, kb_id: str, folder_path: str, file_name: str):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"
        
        success, result = self.file_service.get_file_detail(kb_id, folder_path, file_name)
        return R.ok(result) if success else R.fail(result)

    @delete(
        path='/{kb_id}/delete/{folder_path:path}/{file_name}',
        summary="删除文件/文件夹",
        response_model=R[str],
        responses={
            "200": {"model": R[str]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def delete_node(self, kb_id: str, folder_path: str, file_name: str):
        # 处理路径，确保格式正确
        if not folder_path or not folder_path.startswith("/"):
            folder_path = "/" + folder_path if folder_path else "/"
        
        success, result = self.file_service.delete_node(kb_id, folder_path, file_name)
        return R.ok(result) if success else R.fail(result)
