import logging
import uuid

from fastapi import HTTPException
from app.module.db_module.models import CollectionItem, KbFile
from app.module.db_module.service import DBService
from app.shared.parse.parse_service import ParseService
from app.shared.embedding.embedding_service import EmbeddingService
from app.common.response import R
from app.common.types import UserContext
from canary_framework import service, on_init, Context
from canary_framework.web.fastapi import web

logger = logging.getLogger(__name__)


@web()
@service(name="CollectionService", deps=[DBService, EmbeddingService])
class CollectionService:
    @on_init
    def init(self, ctx: Context):
        self._parse_svc = ParseService()

    async def submit(self, user: UserContext, url: str) -> R[dict]:
        item_id = f"col_{uuid.uuid4().hex[:20]}"
        item = CollectionItem(
            id=item_id,
            user_id=user.user_id,
            url=url,
            status="pending",
        )
        async with self.db_service.transaction() as session:
            repo = self.db_service.collection_repo(session)
            await repo.create(item)

        import asyncio
        asyncio.create_task(self._process_collection(item_id))

        return R.ok({"id": item_id, "url": url, "status": "pending"})

    async def _process_collection(self, item_id: str):
        try:
            async with self.db_service.transaction() as session:
                repo = self.db_service.collection_repo(session)
                item = await repo.get_by_id(item_id)
                if not item:
                    return

                parsed_text, metadata = await self._parse_svc.parse(url=item.url)
                item.content = parsed_text
                item.title = metadata.get("title", "")
                item.status = "success"
                await repo.update(item)
            logger.info(f"Collection completed: id={item_id}")
        except Exception as e:
            logger.error(f"Collection failed: id={item_id}, error={e}")
            try:
                async with self.db_service.transaction() as session:
                    repo = self.db_service.collection_repo(session)
                    item = await repo.get_by_id(item_id)
                    if item:
                        item.status = "failed"
                        await repo.update(item)
            except Exception:
                pass

    async def list_items(self, user: UserContext, current: int = 1, size: int = 20) -> R[dict]:
        async with self.db_service.transaction() as session:
            repo = self.db_service.collection_repo(session)
            items, total = await repo.list_by_user(user.user_id, current, size)
            records = [{
                "id": i.id,
                "url": i.url,
                "title": i.title,
                "status": i.status,
                "is_imported": i.is_imported,
                "created_at": i.created_at.isoformat(),
            } for i in items]
            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": records,
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_item(self, item_id: str, user: UserContext) -> R[dict]:
        async with self.db_service.transaction() as session:
            repo = self.db_service.collection_repo(session)
            item = await repo.get_by_id(item_id)
            if not item:
                raise HTTPException(status_code=404, detail="采集记录不存在")
            if item.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")
            return R.ok({
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "content": item.content,
                "status": item.status,
                "is_imported": item.is_imported,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            })

    async def delete_item(self, item_id: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            repo = self.db_service.collection_repo(session)
            item = await repo.get_by_id(item_id)
            if not item:
                raise HTTPException(status_code=404, detail="采集记录不存在")
            if item.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")
            await repo.delete(item_id)
            return R.ok(msg="删除成功")

    async def import_to_kb(self, item_id: str, kb_id: str, user: UserContext) -> R[dict]:
        async with self.db_service.transaction() as session:
            repo = self.db_service.collection_repo(session)
            kb_repo = self.db_service.kb_repo(session)
            file_repo = self.db_service.file_repo(session)

            item = await repo.get_by_id(item_id)
            if not item:
                raise HTTPException(status_code=404, detail="采集记录不存在")
            if item.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")
            if item.status != "success":
                raise HTTPException(status_code=409, detail="仅成功状态的采集可导入")
            if not item.content:
                raise HTTPException(status_code=409, detail="采集无内容")
            if item.is_imported:
                raise HTTPException(status_code=409, detail="已导入")

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")

            title = item.title or item.url.split("/")[-1] or "untitled"
            file_name = title.strip().replace("/", "_")[:200]
            unique_name = await file_repo.get_unique_name(kb_id, "/", file_name)

            file_id = f"file_{uuid.uuid4().hex[:20]}"
            f = KbFile(
                id=file_id,
                kb_id=kb_id,
                name=unique_name,
                file_type="txt",
                file_size=len(item.content.encode("utf-8")),
                parent_path="/",
                parsed_text=item.content,
                status="parsed",
                created_by=user.user_id,
            )
            await file_repo.create(f)

            item.is_imported = True
            await repo.update(item)

            self.embedding_service.submit({"file_id": file_id, "kb_id": kb_id})

            logger.info(f"Collection imported to KB: item_id={item_id}, kb_id={kb_id}, file_id={file_id}")
            return R.ok({
                "file_id": file_id,
                "name": unique_name,
                "status": "parsed",
            })
