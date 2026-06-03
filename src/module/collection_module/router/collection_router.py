from canary_framework import router, get, post, delete

from app import get_current_user
from src.common.pagination import parse_pagination
from app import CollectionService
from app import AuthService


@router(name="collection_api", prefix="/api/v1/collections", deps=[CollectionService, AuthService])
class CollectionRouter:
    collection_service: CollectionService
    auth_service: AuthService

    @post("/", tags=["采集"], summary="提交 URL 采集")
    async def submit(self, request):
        user = await get_current_user(request, self.auth_service)
        body = await request.json()
        url = body.get("url", "")
        return await self.collection_service.submit(user, url)

    @get("/", tags=["采集"], summary="采集列表")
    async def list_items(self, request):
        user = await get_current_user(request, self.auth_service)
        current, size = parse_pagination(request)
        return await self.collection_service.list_items(user, current, size)

    @get("/{item_id}", tags=["采集"], summary="采集详情")
    async def get_item(self, request):
        user = await get_current_user(request, self.auth_service)
        item_id = request.path_params["item_id"]
        return await self.collection_service.get_item(item_id, user)

    @delete("/{item_id}", tags=["采集"], summary="删除采集")
    async def delete_item(self, request):
        user = await get_current_user(request, self.auth_service)
        item_id = request.path_params["item_id"]
        return await self.collection_service.delete_item(item_id, user)

    @post("/{item_id}/import/{kb_id}", tags=["采集"], summary="导入到知识库")
    async def import_to_kb(self, request):
        user = await get_current_user(request, self.auth_service)
        item_id = request.path_params["item_id"]
        kb_id = request.path_params["kb_id"]
        return await self.collection_service.import_to_kb(item_id, kb_id, user)
