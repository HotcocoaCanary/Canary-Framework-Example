import asyncio
import logging
import threading
import uuid
from queue import Queue

from fastapi import HTTPException, Depends, Query, Request

from app.common.depends import get_current_user
from app.common.response import R
from app.common.types import UserContext
from app.module.db_module.models import KbFile
from app.module.db_module.service import DBService
from app.shared.aliyun.service.oss_service import OSSClient
from app.shared.embedding.embedding_service import EmbeddingService
from app.shared.parse.parse_service import ParseService
from canary_framework import service, on_init, on_start, on_end, Context
from canary_framework.web.fastapi import web

logger = logging.getLogger(__name__)


@web()
@service(name="FileService", deps=[DBService, OSSClient])
class FileService:
    @on_init
    def init(self, ctx: Context):
        self._queue: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = True
        self._parse_svc = ParseService()
        self._embed_svc: EmbeddingService | None = None

    @on_start
    async def start(self, ctx: Context):
        self._embed_svc = ctx.resolve(EmbeddingService)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("FileService background worker started")

    @on_end
    async def end(self):
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("FileService shutdown")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker_loop())

    async def _worker_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1)
            except Exception:
                continue
            if item is None:
                break
            await self._process_file(item)

    async def _process_file(self, item: dict):
        file_id = item.get("file_id")
        kb_id = item.get("kb_id")
        try:
            async with self.db_service.transaction() as session:
                file_repo = self.db_service.file_repo(session)
                f = await file_repo.get_by_id(file_id)
                if not f:
                    return
                if f.status != "pending":
                    return

                data = self.oss_client.download(item["oss_key"])
                parsed_text, metadata = await self._parse_svc.parse(file=data, file_name=f.name)

                f.file_size = metadata.get("file_size", len(data))
                f.parsed_text = parsed_text
                f.status = "parsed"
                await file_repo.update(f)

            self._embed_svc.submit({"file_id": file_id, "kb_id": kb_id})
            logger.info(f"Parse completed: file_id={file_id}")
        except Exception as e:
            logger.error(f"File processing failed: file_id={file_id}, error={e}")
            try:
                async with self.db_service.transaction() as session:
                    file_repo = self.db_service.file_repo(session)
                    f = await file_repo.get_by_id(file_id)
                    if f:
                        f.status = "failed"
                        f.error_msg = str(e)
                        await file_repo.update(f)
            except Exception:
                pass

    async def upload_files(
            self,
            kb_id: str,
            folder_path: str,
            user: UserContext,
            files: list[tuple[str, bytes, str]],
    ) -> R[list[dict]]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            file_repo = self.db_service.file_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可上传")

            results = []
            for filename, data, content_type in files:
                parts = filename.split("/")
                file_name_only = parts[-1]
                parent = folder_path
                if len(parts) > 1:
                    parent = self._join_path(folder_path, "/".join(parts[:-1]))
                    await self._ensure_folder_path(session, file_repo, kb_id, parent, user.user_id)

                unique_name = await file_repo.get_unique_name(kb_id, parent, file_name_only)
                ext = file_name_only.rsplit(".", 1)[-1].lower() if "." in file_name_only else file_name_only.lower()

                oss_key = self.oss_client.build_key(user.user_id, user.username, kb_id, self._join_path(parent, unique_name))
                oss_url = self.oss_client.upload(oss_key, data, content_type)

                file_id = f"file_{uuid.uuid4().hex[:20]}"
                f = KbFile(
                    id=file_id,
                    kb_id=kb_id,
                    name=unique_name,
                    file_type=ext,
                    file_size=len(data),
                    parent_path=parent,
                    oss_url=oss_url,
                    status="pending",
                    created_by=user.user_id,
                )
                await file_repo.create(f)

                self._queue.put({"file_id": file_id, "kb_id": kb_id, "oss_key": oss_key})

                results.append({
                    "file_id": file_id,
                    "name": unique_name,
                    "file_type": ext,
                    "file_size": len(data),
                    "status": "pending",
                })

            return R.ok(results)

    async def create_folder(
            self,
            kb_id: str,
            folder_path: str,
            user: UserContext,
            name: str,
    ) -> R[dict]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            file_repo = self.db_service.file_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")

            unique_name = await file_repo.get_unique_name(kb_id, folder_path, name)
            file_id = f"file_{uuid.uuid4().hex[:20]}"
            f = KbFile(
                id=file_id,
                kb_id=kb_id,
                name=unique_name,
                file_type=None,
                parent_path=folder_path,
                created_by=user.user_id,
            )
            await file_repo.create(f)
            return R.ok({"file_id": file_id, "name": unique_name, "file_type": None})

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
            file_repo = self.db_service.file_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")

            files, total = await file_repo.list_children(kb_id, folder_path, current, size)

            records = []
            for f in files:
                records.append({
                    "file_id": f.id,
                    "name": f.name,
                    "file_type": f.file_type,
                    "file_size": f.file_size if f.file_type else None,
                    "status": f.status,
                    "updated_at": f.updated_at.isoformat(),
                })

            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": records,
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_file_detail(self, kb_id: str, folder_path: str, file_name: str, user: UserContext) -> R[dict]:
        async with self.db_service.transaction() as session:
            file_repo = self.db_service.file_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            f = await file_repo.get_by_path(kb_id, folder_path, file_name)
            if not f or f.file_type is None:
                raise HTTPException(status_code=404, detail="文件不存在")

            chunk_count = await chunk_repo.count_by_file_id(f.id)

            return R.ok({
                "file_id": f.id,
                "name": f.name,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "status": f.status,
                "oss_url": f.oss_url,
                "chunk_count": chunk_count,
                "created_at": f.created_at.isoformat(),
                "updated_at": f.updated_at.isoformat(),
            })

    async def delete_node(self, kb_id: str, folder_path: str, name: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            file_repo = self.db_service.file_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")

            f = await file_repo.get_by_path(kb_id, folder_path, name)
            if not f:
                raise HTTPException(status_code=404, detail="文件/文件夹不存在")

            if f.file_type is None:
                all_files = await file_repo.list_by_kb(kb_id)
                prefix = self._join_path(folder_path, name)
                for child in all_files:
                    if child.parent_path and (
                            child.parent_path == prefix or child.parent_path.startswith(prefix + "/")):
                        await chunk_repo.delete_by_file_id(child.id)
                        await file_repo.delete_by_id(child.id)
                await file_repo.delete_by_parent_and_name(kb_id, folder_path, name)
            else:
                await chunk_repo.delete_by_file_id(f.id)
                await file_repo.delete_by_id(f.id)

            logger.info(f"Node deleted: kb_id={kb_id}, path={self._join_path(folder_path, name)}")
            return R.ok(msg="删除成功")

    def _join_path(self, parent: str, name: str) -> str:
        parent = parent.rstrip("/")
        name = name.strip("/")
        if not parent:
            return "/" + name
        return parent + "/" + name

    async def _ensure_folder_path(self, session, file_repo, kb_id: str, folder_path: str, user_id: str) -> None:
        if not folder_path or folder_path == "/":
            return
        parts = folder_path.strip("/").split("/")
        current = ""
        for part in parts:
            current_path = "/" + part if not current else current + "/" + part
            parent_path = "/" + "/".join(parts[:parts.index(part)]) if parts.index(part) > 0 else "/"
            if parts.index(part) == 0:
                parent_path = "/"
            existing = await file_repo.get_by_path(kb_id, parent_path, part)
            if not existing:
                folder = KbFile(
                    id=f"file_{uuid.uuid4().hex[:20]}",
                    kb_id=kb_id,
                    name=part,
                    file_type=None,
                    parent_path=parent_path,
                    created_by=user_id,
                )
                await file_repo.create(folder)
            current = current_path
