from canary_framework import router, get, post, delete

from app import get_current_user
from src.common.pagination import parse_pagination
from src.module.file_module.service.file_service import FileService
from app import AuthService


@router(name="file_api", prefix="/api/v1/kb", deps=[FileService, AuthService])
class FileRouter:
    file_service: FileService
    auth_service: AuthService

    @staticmethod
    def _normalize_folder(request) -> str:
        folder_path = request.path_params.get("folder_path", "")
        return "/" + folder_path if folder_path else "/"

    @post("/{kb_id}/files/{folder_path:path}/", tags=["文件管理"],
          summary="上传文件 / 创建文件夹",
          description="multipart/form-data 上传文件; application/json 创建空文件夹")
    async def upload(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        folder_path = self._normalize_folder(request)
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            form = await request.form()
            uploaded_files = form.getlist("files")
            files = []
            for f in uploaded_files:
                if hasattr(f, "filename") and hasattr(f, "file"):
                    data = await f.read()
                    files.append((f.filename, data, f.content_type or "application/octet-stream"))
            return await self.file_service.upload_files(kb_id, folder_path, user, files)

        elif "application/json" in content_type:
            body = await request.json()
            name = body.get("name", "")
            return await self.file_service.create_folder(kb_id, folder_path, user, name)

        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="不支持的内容类型")

    @get("/{kb_id}/files/{folder_path:path}/", tags=["文件管理"], summary="文件/文件夹列表")
    async def list_nodes(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        folder_path = self._normalize_folder(request)
        current, size = parse_pagination(request)
        return await self.file_service.list_nodes(kb_id, folder_path, user, current, size)

    @get("/{kb_id}/files/{folder_path:path}/{file_name}/detail", tags=["文件管理"], summary="文件详情")
    async def get_file_detail(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        folder_path = self._normalize_folder(request)
        file_name = request.path_params["file_name"]
        return await self.file_service.get_file_detail(kb_id, folder_path, file_name, user)

    @delete("/{kb_id}/files/{folder_path:path}/{file_name}", tags=["文件管理"], summary="删除文件/文件夹")
    async def delete_node(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        folder_path = self._normalize_folder(request)
        file_name = request.path_params["file_name"]
        return await self.file_service.delete_node(kb_id, folder_path, file_name, user)
