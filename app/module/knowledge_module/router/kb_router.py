from typing import Optional

from canary_framework.web.fastapi import router, get, post, put, delete
from fastapi import Depends, Query

from app.common.depends import get_current_user
from app.module.knowledge_module.schema import CreateKbRequest, UpdateKbRequest
from app.module.knowledge_module.service.kb_service import KbService


@router(prefix="/api/v1/knowledge-bases", deps=[KbService])
class KbRouter:
    kb_service: KbService

    @post("/", tags=["知识库"], summary="创建知识库", description="创建一个新的知识库，当前用户自动成为 owner")
    async def create(self, req: CreateKbRequest, user=Depends(get_current_user)):
        return await self.kb_service.create_kb(user, req)

    @get("/", tags=["知识库"], summary="我的知识库列表", description="获取当前用户创建或加入的所有知识库")
    async def list_kbs(
            self,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            user=Depends(get_current_user),
    ):
        return await self.kb_service.list_user_kbs(user, current, size)

    @get("/public", tags=["知识库"], summary="公开知识库列表", description="无需认证，浏览所有公开知识库")
    async def list_public(
            self,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            keyword: Optional[str] = Query(None, description="搜索关键词"),
    ):
        return await self.kb_service.list_public_kbs(current, size, keyword)

    @get("/shared/{share_token}", tags=["知识库"], summary="通过分享链接查看知识库")
    async def get_shared(self, share_token: str):
        return await self.kb_service.get_shared_kb(share_token)

    @get("/me/storage", tags=["知识库"], summary="用户空间统计",
         description="统计当前用户作为创建者的所有知识库文件大小")
    async def get_storage(self, user=Depends(get_current_user)):
        return await self.kb_service.get_user_storage(user)

    @get("/{kb_id}", tags=["知识库"], summary="知识库详情")
    async def view_kb(self, kb_id: str, user=Depends(get_current_user)):
        return await self.kb_service.get_kb(kb_id, user)

    @put("/{kb_id}", tags=["知识库"], summary="更新知识库")
    async def update(self, kb_id: str, req: UpdateKbRequest, user=Depends(get_current_user)):
        return await self.kb_service.update_kb(kb_id, user, req)

    @delete("/{kb_id}", tags=["知识库"], summary="删除知识库", description="仅创建者可操作，级联删除所有文件、分块和成员")
    async def delete(self, kb_id: str, user=Depends(get_current_user)):
        return await self.kb_service.delete_kb(kb_id, user)

    @post("/{kb_id}/share-link", tags=["知识库"], summary="生成分享链接",
          description="仅 shared 权限知识库且创建者可操作")
    async def create_share_link(self, kb_id: str, user=Depends(get_current_user)):
        return await self.kb_service.create_share_link(kb_id, user)

    @post("/{kb_id}/join", tags=["知识库"], summary="加入知识库")
    async def join(self, kb_id: str, user=Depends(get_current_user)):
        return await self.kb_service.join_kb(kb_id, user)
