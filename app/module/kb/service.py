import uuid
from typing import Optional

from canary_framework import service
from fastapi import HTTPException

from app.module.db.module import DBModule
from app.module.db.repository.kb_chunk_repository import KbChunkRepository
from app.module.db.repository.kb_file_repository import KBFileRepository
from app.module.db.repository.kb_member_repostory import KBMemberRepository
from app.module.db.repository.knowledge_bases_repository import KnowledgeBaseRepository
from app.common.response import R
from app.module.kb.schema import CreateKbRequest, UpdateKbRequest, KbResponse, ShareLinkResponse, StorageResponse
from app.module.db.models import KnowledgeBase, KbMember


@service()
class KbService:
    knowledge_base_repo: KnowledgeBaseRepository
    kb_member_repo: KBMemberRepository
    kb_file_repo: KBFileRepository
    kb_chunk_repo: KbChunkRepository

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

    def create_kb(self, request: CreateKbRequest, user_id: str = "test_user") -> tuple[bool, KbResponse | str]:
        try:
            kb = self.knowledge_base_repo.create_knowledge_base(
                name=request.name,
                created_by=user_id,
                description=request.description,
                permission=request.permission
            )
            self.kb_member_repo.add_member(kb.id, user_id, role="owner")
            return True, self._kb_to_response(kb)
        except Exception as e:
            return False, str(e)

    def list_user_kbs(self, user_id: str = "test_user", page: int = 1, size: int = 20) -> tuple[bool, dict]:
        try:
            skip = (page - 1) * size
            
            member_kb_ids = self.kb_member_repo.list_user_kbs(user_id)
            owned_kbs = self.knowledge_base_repo.list_knowledge_bases(user_id, skip=0, limit=10000)
            
            all_kb_ids = set(member_kb_ids) | {kb.id for kb in owned_kbs}
            
            all_kbs = []
            for kb_id in all_kb_ids:
                kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
                if kb:
                    all_kbs.append(kb)
            
            total = len(all_kbs)
            all_kbs.sort(key=lambda x: x.updated_at, reverse=True)
            start = skip
            records = all_kbs[start:start + size]
            
            result = [self._kb_to_response(kb).model_dump() for kb in records]
            pages = (total + size - 1) // size if size > 0 else 0
            
            return True, {
                "records": result,
                "total": total,
                "size": size,
                "current": page,
                "pages": pages
            }
        except Exception as e:
            return False, str(e)

    def get_kb(self, kb_id: str, user_id: str = "test_user") -> tuple[bool, KbResponse | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            
            member = self.kb_member_repo.get_member(kb_id, user_id)
            if kb.permission == "private" and not member:
                return False, "无权限"
            
            return True, self._kb_to_response(kb)
        except Exception as e:
            return False, str(e)

    def update_kb(self, kb_id: str, request: UpdateKbRequest, user_id: str = "test_user") -> tuple[bool, KbResponse | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可编辑"
            
            update_kwargs = {}
            if request.name is not None:
                update_kwargs["name"] = request.name
            if request.description is not None:
                update_kwargs["description"] = request.description
            if request.permission is not None:
                if request.permission not in ("private", "shared"):
                    return False, "permission 仅允许 private/shared"
                update_kwargs["permission"] = request.permission
            
            kb = self.knowledge_base_repo.update_knowledge_base(kb_id, **update_kwargs)
            return True, self._kb_to_response(kb)
        except Exception as e:
            return False, str(e)

    def delete_kb(self, kb_id: str, user_id: str = "test_user") -> tuple[bool, str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可操作"
            
            self.kb_chunk_repo.delete_chunks_by_kb(kb_id)
            self.kb_file_repo.delete_files_by_kb(kb_id)
            self.kb_member_repo.remove_members_by_kb(kb_id)
            self.knowledge_base_repo.delete_knowledge_base(kb_id)
            
            return True, "删除成功"
        except Exception as e:
            return False, str(e)

    def create_share_link(self, kb_id: str, user_id: str = "test_user") -> tuple[bool, ShareLinkResponse | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可操作"
            if kb.permission != "shared":
                return False, "仅共享知识库可生成分享链接"
            
            share_token = uuid.uuid4().hex[:16]
            kb = self.knowledge_base_repo.update_knowledge_base(kb_id, share_token=share_token)
            share_url = f"/shared/{share_token}"
            
            return True, ShareLinkResponse(share_url=share_url, share_token=share_token)
        except Exception as e:
            return False, str(e)

    def list_public_kbs(self, keyword: Optional[str] = None, page: int = 1, size: int = 20) -> tuple[bool, dict]:
        try:
            skip = (page - 1) * size
            kbs, total = self.knowledge_base_repo.list_public_knowledge_bases(keyword=keyword, skip=skip, limit=size)
            
            records = [self._kb_to_response(kb).model_dump() for kb in kbs]
            pages = (total + size - 1) // size if size > 0 else 0
            
            return True, {
                "records": records,
                "total": total,
                "size": size,
                "current": page,
                "pages": pages
            }
        except Exception as e:
            return False, str(e)

    def get_shared_kb(self, share_token: str) -> tuple[bool, KbResponse | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base_by_share_token(share_token)
            if not kb:
                return False, "分享链接无效"
            return True, self._kb_to_response(kb)
        except Exception as e:
            return False, str(e)

    def join_kb(self, kb_id: str, user_id: str = "test_user") -> tuple[bool, str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            
            existing = self.kb_member_repo.get_member(kb_id, user_id)
            if existing:
                return True, "已加入"
            
            self.kb_member_repo.add_member(kb_id, user_id, role="member")
            return True, "加入成功"
        except Exception as e:
            return False, str(e)

    def get_user_storage(self, user_id: str = "test_user") -> tuple[bool, StorageResponse | str]:
        try:
            used = self.kb_file_repo.total_size_by_owner(user_id)
            used_mb = used / (1024 * 1024)
            used_formatted = f"{used_mb:.2f} MB" if used > 0 else "0 MB"
            
            return True, StorageResponse(used_bytes=used, used_formatted=used_formatted)
        except Exception as e:
            return False, str(e)