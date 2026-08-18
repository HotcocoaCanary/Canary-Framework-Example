from canary_framework.web import delete, get, patch, post

from app.common.response import R, PageR
from app.module.file.schema import FileResponse, CreateFileRequest, PatchFileRequest
from app.module.file.service import FileService


class FileRouter:
    file_service: FileService

    # Canary 0.9 uses ordinary Starlette path templates.  ``folder_path`` is
    # intentionally a query parameter so it can contain nested ``/`` values.

    @post(
        '/file/{kb_id}',
    )
    async def create(self, kb_id: str, folder_path: str, body: CreateFileRequest) -> R[dict]:
        success, result = self.file_service.create(kb_id, folder_path, body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/file/{kb_id}',
    )
    async def list_nodes(self, kb_id: str, folder_path: str = "", page: int = 1, size: int = 20) -> PageR[FileResponse]:
        success, result = self.file_service.list_nodes(kb_id, folder_path, page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/file/{kb_id}',
    )
    async def delete_by_path(self, kb_id: str, folder_path: str) -> R[str]:
        success, result = self.file_service.delete_by_path(kb_id, folder_path)
        return R.ok(result) if success else R.fail(result)

    @patch(
        '/file/{kb_id}',
    )
    async def update_by_path(self, kb_id: str, folder_path: str, body: PatchFileRequest) -> R[dict]:
        success, result = self.file_service.update_by_path(kb_id, folder_path, body)
        return R.ok(result) if success else R.fail(result)
