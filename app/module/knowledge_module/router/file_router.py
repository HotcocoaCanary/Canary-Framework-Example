from fastapi import Depends, Query, Request

from app.common.depends import get_current_user
from app.module.knowledge_module.schema import CreateFolderRequest
from cf.web.fastapi import router, get, post, delete, RouterContext


@router(prefix="/api/v1/knowledge-bases/file-op")
class FileRouter:
    def __init__(self, ctx: RouterContext):
        self.svc = ctx.service

    @post("/{kb_id}/{folder_path:path}/", tags=["文件管理"],
          summary="上传文件 / 创建文件夹",
          description="multipart/form-data 上传文件; application/json 创建空文件夹")
    async def upload(
            self,
            kb_id: str,
            folder_path: str,
            request: Request,
            user=Depends(get_current_user),
    ):
        folder_path = "/" + folder_path if folder_path else "/"
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            form = await request.form()
            uploaded_files = form.getlist("files")
            files = []
            for f in uploaded_files:
                if hasattr(f, "filename") and hasattr(f, "file"):
                    data = await f.read()
                    files.append((f.filename, data, f.content_type or "application/octet-stream"))
            return await self.svc.upload_files(kb_id, folder_path, user, files)

        elif "application/json" in content_type:
            body = await request.json()
            req = CreateFolderRequest(**body)
            return await self.svc.create_folder(kb_id, folder_path, user, req)

        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="不支持的内容类型")

    @get("/{kb_id}/{folder_path:path}/", tags=["文件管理"], summary="文件/文件夹列表",
         description="列出指定路径下的所有文件和子文件夹")
    async def list_nodes(
            self,
            kb_id: str,
            folder_path: str,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            user=Depends(get_current_user),
    ):
        folder_path = "/" + folder_path if folder_path else "/"
        return await self.svc.list_nodes(kb_id, folder_path, user, current, size)

    @get("/{kb_id}/{folder_path:path}/{file_name}/detail", tags=["文件管理"], summary="文件详情",
         description="获取文件的 OSS URL、解析状态、chunk 数量等详细信息")
    async def get_file_detail(
            self,
            kb_id: str,
            folder_path: str,
            file_name: str,
            user=Depends(get_current_user),
    ):
        folder_path = "/" + folder_path if folder_path else "/"
        return await self.svc.get_file_detail(kb_id, folder_path, file_name, user)

    @delete("/{kb_id}/{folder_path:path}/{file_name}", tags=["文件管理"], summary="删除文件/文件夹",
            description="文件夹会递归删除内部所有文件和子文件夹")
    async def delete_node(
            self,
            kb_id: str,
            folder_path: str,
            file_name: str,
            user=Depends(get_current_user),
    ):
        folder_path = "/" + folder_path if folder_path else "/"
        return await self.svc.delete_node(kb_id, folder_path, file_name, user)
