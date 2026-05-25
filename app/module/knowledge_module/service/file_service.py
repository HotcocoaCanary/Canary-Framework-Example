import logging
import uuid

from fastapi import HTTPException

from app.module.db_module.models import KbNode, KbFileRecord, ParseTask
from app.module.db_module.service import DBService
from app.module.knowledge_module.router.file_router import FileRouter
from app.module.knowledge_module.schema import (
    CreateFolderRequest,
    FileItemResponse,
    FileDetailResponse,
    ParseTaskResponse,
    ParseTaskFileItem,
)
from app.shared.aliyun.service.oss_service import OSSClient
from app.common.response import R
from app.common.types import UserContext
from canary_framework import service, on_init, Context
from canary_framework.web.fastapi import web

logger = logging.getLogger(__name__)


@web(routers=[FileRouter])
@service(name="FileService", deps=[DBService, OSSClient])
class FileService:
    @on_init
    def init(self, ctx: Context):
        pass

    async def upload_files(
            self,
            kb_id: str,
            folder_path: str,
            user: UserContext,
            files: list[tuple[str, bytes, str]],
    ) -> R[ParseTaskResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)
            node_repo = self.db_service.node_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)
            parse_repo = self.db_service.parse_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可上传")

            task_id = f"task_{uuid.uuid4().hex[:20]}"
            task = ParseTask(
                id=task_id,
                kb_id=kb_id,
                created_by=user.user_id,
            )
            await parse_repo.create(task)

            file_list = []
            for filename, data, content_type in files:
                parts = filename.split("/")
                file_name_only = parts[-1]
                if len(parts) > 1:
                    sub_path = "/".join(parts[:-1])
                    full_parent = self._join_path(folder_path, sub_path)
                    await self._ensure_folder_path(session, node_repo, kb_id, full_parent, user.user_id)
                else:
                    full_parent = folder_path

                unique_name = await node_repo.get_unique_name(kb_id, full_parent, file_name_only)
                full_path = self._join_path(full_parent, unique_name)
                ext = file_name_only.rsplit(".", 1)[-1].lower() if "." in file_name_only else file_name_only.lower()

                oss_key = self.oss_client.build_key(user.user_id, user.username, kb_id, full_path)
                oss_url = self.oss_client.upload(oss_key, data, content_type)

                node_id = f"nd_{uuid.uuid4().hex[:20]}"
                node = KbNode(
                    id=node_id,
                    kb_id=kb_id,
                    name=unique_name,
                    node_type=ext,
                    size=len(data),
                    parent_path=full_parent,
                    full_path=full_path,
                    oss_key=oss_key,
                    oss_url=oss_url,
                    created_by=user.user_id,
                )
                await node_repo.create(node)

                record = KbFileRecord(
                    file_id=node_id,
                    status="pending",
                    parse_task_id=task_id,
                )
                await file_record_repo.create(record)

                file_list.append(ParseTaskFileItem(
                    file_id=node_id,
                    file_name=unique_name,
                    file_type=ext,
                    status="pending",
                ))

            return R.ok(ParseTaskResponse(
                parse_task_id=task_id,
                file_list=file_list,
                created_at=task.created_at,
            ))

    async def create_folder(
            self,
            kb_id: str,
            folder_path: str,
            user: UserContext,
            req: CreateFolderRequest,
    ) -> R[ParseTaskResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)
            node_repo = self.db_service.node_repo(session)
            parse_repo = self.db_service.parse_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")

            unique_name = await node_repo.get_unique_name(kb_id, folder_path, req.name)
            full_path = self._join_path(folder_path, unique_name)

            node = KbNode(
                id=f"nd_{uuid.uuid4().hex[:20]}",
                kb_id=kb_id,
                name=unique_name,
                node_type=None,
                parent_path=folder_path,
                full_path=full_path,
                created_by=user.user_id,
            )
            await node_repo.create(node)

            task_id = f"task_{uuid.uuid4().hex[:20]}"
            task = ParseTask(id=task_id, kb_id=kb_id, created_by=user.user_id)
            await parse_repo.create(task)

            return R.ok(ParseTaskResponse(
                parse_task_id=task_id,
                file_list=[],
                created_at=task.created_at,
            ))

    async def list_nodes(
            self,
            kb_id: str,
            folder_path: str,
            user: UserContext,
            current: int = 1,
            size: int = 20,
    ) -> R[dict]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)
            node_repo = self.db_service.node_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")

            nodes, total = await node_repo.list_children(kb_id, folder_path, current, size)

            records = []
            for node in nodes:
                status = None
                if node.node_type is not None:
                    record = await file_record_repo.get_by_file_id(node.id)
                    if record:
                        status = record.status
                records.append(FileItemResponse(
                    id=node.id,
                    name=node.name,
                    node_type=node.node_type,
                    size=node.size if node.node_type else None,
                    status=status,
                    updated_at=node.updated_at,
                ))

            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in records],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_file_detail(self, kb_id: str, folder_path: str, file_name: str, user: UserContext) -> R[
        FileDetailResponse]:
        async with self.db_service.transaction() as session:
            node_repo = self.db_service.node_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            full_path = self._join_path(folder_path, file_name)
            node = await node_repo.get_by_path(kb_id, full_path)
            if not node or node.node_type is None:
                raise HTTPException(status_code=404, detail="文件不存在")

            record = await file_record_repo.get_by_file_id(node.id)
            chunks = await chunk_repo.get_by_file_id(node.id)

            return R.ok(FileDetailResponse(
                id=node.id,
                name=node.name,
                node_type=node.node_type,
                size=node.size,
                status=record.status if record else None,
                oss_url=node.oss_url,
                chunk_count=len(chunks),
                parse_task_id=record.parse_task_id if record else None,
                updated_at=node.updated_at,
            ))

    async def delete_node(self, kb_id: str, folder_path: str, name: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            node_repo = self.db_service.node_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")

            full_path = self._join_path(folder_path, name)
            node = await node_repo.get_by_path(kb_id, full_path)
            if not node:
                raise HTTPException(status_code=404, detail="文件/文件夹不存在")

            if node.node_type is None:
                nodes_to_delete = await node_repo.list_by_kb(kb_id)
                node_ids = [n.id for n in nodes_to_delete if
                            n.full_path == full_path or n.full_path.startswith(full_path + "/")]
                await file_record_repo.delete_by_file_ids(node_ids)
                for nid in node_ids:
                    await chunk_repo.delete_by_file_id(nid)
                await node_repo.delete_by_path_prefix(kb_id, full_path)
            else:
                await chunk_repo.delete_by_file_id(node.id)
                await file_record_repo.delete_by_file_id(node.id)
                await node_repo.delete_by_id(node.id)

            logger.info(f"Node deleted: kb_id={kb_id}, path={full_path}")
            return R.ok(msg="删除成功")

    def _join_path(self, parent: str, name: str) -> str:
        parent = parent.rstrip("/")
        name = name.strip("/")
        if not parent:
            return "/" + name
        return parent + "/" + name

    async def _ensure_folder_path(self, session, node_repo, kb_id: str, folder_path: str, user_id: str) -> None:
        if not folder_path or folder_path == "/":
            return
        parts = folder_path.strip("/").split("/")
        current = ""
        for part in parts:
            current_path = "/" + part if not current else current + "/" + part
            existing = await node_repo.get_by_path(kb_id, current_path)
            if not existing:
                folder = KbNode(
                    id=f"nd_{uuid.uuid4().hex[:20]}",
                    kb_id=kb_id,
                    name=part,
                    node_type=None,
                    parent_path=current,
                    full_path=current_path,
                    created_by=user_id,
                )
                await node_repo.create(folder)
            current = current_path
