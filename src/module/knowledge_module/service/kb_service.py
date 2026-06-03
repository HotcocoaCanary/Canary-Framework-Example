import logging
import uuid
from datetime import datetime
from typing import Optional

from canary_framework import service, after_config
from fastapi import HTTPException

from app import R
from src.common.types import UserContext
from src.module.db_module.models import KnowledgeBase, KbMember
from src.module.db_module.service import DBService
from src.module.knowledge_module.schema import (
    CreateKbRequest,
    UpdateKbRequest,
    KbResponse,
    ShareLinkResponse,
)

logger = logging.getLogger(__name__)


@service(name="KbService", deps=[DBService])
class KbService:
    @after_config
    def setup(self):
        pass

    def _kb_to_response(self, kb: KnowledgeBase, file_count: int = 0, total_size: int = 0) -> KbResponse:
        return KbResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            permission=kb.permission,
            share_token=kb.share_token,
            created_by=kb.created_by,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            file_count=file_count,
            total_size=total_size,
        )

    async def create_kb(self, user: UserContext, req: CreateKbRequest) -> R[KbResponse]:
        kb_id = f"kb_{uuid.uuid4().hex[:20]}"
        now = datetime.utcnow()
        kb = KnowledgeBase(
            id=kb_id,
            name=req.name,
            description=req.description,
            permission=req.permission,
            created_by=user.user_id,
            created_at=now,
            updated_at=now,
        )
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)
            await kb_repo.create(kb)
            member = KbMember(kb_id=kb_id, user_id=user.user_id, role="owner", joined_at=now)
            await member_repo.create(member)

        logger.info(f"KB created: id={kb_id}, name={req.name}, user={user.user_id}")
        return R.ok(self._kb_to_response(kb))

    async def list_user_kbs(self, user: UserContext, current: int = 1, size: int = 20) -> R[dict]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)

            member_kb_ids = await member_repo.list_by_user(user.user_id)
            owned_kbs, owned_total = await kb_repo.list_by_user(user.user_id, current=1, size=10000)

            all_kb_ids = set(member_kb_ids) | {kb.id for kb in owned_kbs}
            all_kbs = []
            for kb_id in all_kb_ids:
                kb = await kb_repo.get_by_id(kb_id)
                if kb:
                    all_kbs.append(kb)

            total = len(all_kbs)
            all_kbs.sort(key=lambda x: x.updated_at, reverse=True)
            start = (current - 1) * size
            records = all_kbs[start:start + size]

            result = []
            for kb in records:
                result.append(self._kb_to_response(kb))

            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in result],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_kb(self, kb_id: str, user: UserContext) -> R[KbResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")

            member = await member_repo.get(kb_id, user.user_id)
            if kb.permission == "private" and not member:
                raise HTTPException(status_code=403, detail="无权限")

            return R.ok(self._kb_to_response(kb))

    async def update_kb(self, kb_id: str, user: UserContext, req: UpdateKbRequest) -> R[KbResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可编辑")

            if req.name is not None:
                kb.name = req.name
            if req.description is not None:
                kb.description = req.description
            if req.permission is not None:
                if req.permission not in ("private", "shared"):
                    raise HTTPException(status_code=400, detail="permission 仅允许 private/shared")
                kb.permission = req.permission

            await kb_repo.update(kb)
            logger.info(f"KB updated: id={kb_id}, user={user.user_id}")
            return R.ok(self._kb_to_response(kb))

    async def delete_kb(self, kb_id: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)
            file_repo = self.db_service.file_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")

            await chunk_repo.delete_by_kb(kb_id)
            await file_repo.delete_by_kb(kb_id)
            await member_repo.delete_by_kb(kb_id)
            await kb_repo.delete(kb_id)

            logger.info(f"KB deleted: id={kb_id}, user={user.user_id}")
            return R.ok(msg="删除成功")

    async def create_share_link(self, kb_id: str, user: UserContext) -> R[ShareLinkResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")
            if kb.created_by != user.user_id:
                raise HTTPException(status_code=403, detail="仅创建者可操作")
            if kb.permission != "shared":
                raise HTTPException(status_code=403, detail="仅共享知识库可生成分享链接")

            kb.share_token = uuid.uuid4().hex[:16]
            await kb_repo.update(kb)
            share_url = f"/shared/{kb.share_token}"
            logger.info(f"Share link created: kb_id={kb_id}")
            return R.ok(ShareLinkResponse(share_url=share_url))

    async def list_public_kbs(self, current: int = 1, size: int = 20, keyword: Optional[str] = None) -> R[dict]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            kbs, total = await kb_repo.list_public(keyword=keyword, current=current, size=size)

            records = [self._kb_to_response(kb) for kb in kbs]
            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in records],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_shared_kb(self, share_token: str) -> R[KbResponse]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            kb = await kb_repo.get_by_share_token(share_token)
            if not kb:
                raise HTTPException(status_code=404, detail="分享链接无效")
            return R.ok(self._kb_to_response(kb))

    async def join_kb(self, kb_id: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            kb_repo = self.db_service.kb_repo(session)
            member_repo = self.db_service.member_repo(session)

            kb = await kb_repo.get_by_id(kb_id)
            if not kb:
                raise HTTPException(status_code=404, detail="知识库不存在")

            existing = await member_repo.get(kb_id, user.user_id)
            if existing:
                return R.ok(msg="已加入")

            member = KbMember(kb_id=kb_id, user_id=user.user_id, role="member")
            await member_repo.create(member)
            logger.info(f"User {user.user_id} joined KB {kb_id}")
            return R.ok(msg="加入成功")

    async def get_user_storage(self, user: UserContext) -> R[dict]:
        async with self.db_service.transaction() as session:
            file_repo = self.db_service.file_repo(session)
            used = await file_repo.total_size_by_owner(user.user_id)
            used_formatted = f"{used / (1024 * 1024):.2f} MB" if used > 0 else "0 MB"
            return R.ok({
                "used_bytes": used,
                "used_formatted": used_formatted,
            })
