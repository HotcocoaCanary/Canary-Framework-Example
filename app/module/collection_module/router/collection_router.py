from canary_framework.web.fastapi import router, get, post, delete
from fastapi import Depends, Query, Request

from app.common.depends import get_current_user
from app.module.collection_module.service.collection_service import CollectionService


@router(prefix="/api/v1/collections", deps=[CollectionService])
class CollectionRouter:
    collection_service: CollectionService

    @post("/", tags=["采集"], summary="提交 URL 采集")
    async def submit(self, request: Request, user=Depends(get_current_user)):
        body = await request.json()
        url = body.get("url", "")
        return await self.collection_service.submit(user, url)

    @get("/", tags=["采集"], summary="采集列表")
    async def list_items(
            self,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            user=Depends(get_current_user),
    ):
        return await self.collection_service.list_items(user, current, size)

    @get("/{item_id}", tags=["采集"], summary="采集详情")
    async def get_item(self, item_id: str, user=Depends(get_current_user)):
        return await self.collection_service.get_item(item_id, user)

    @delete("/{item_id}", tags=["采集"], summary="删除采集")
    async def delete_item(self, item_id: str, user=Depends(get_current_user)):
        return await self.collection_service.delete_item(item_id, user)

    @post("/{item_id}/import/{kb_id}", tags=["采集"], summary="导入到知识库")
    async def import_to_kb(self, item_id: str, kb_id: str, user=Depends(get_current_user)):
        return await self.collection_service.import_to_kb(item_id, kb_id, user)
