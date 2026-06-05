from canary_framework import router, get, post, delete
from canary_framework.core.router import RouterBase

from app.module.collection.schema import SubmitUrlRequest, CollectionItemResponse, ImportToKbResponse
from app.common.response import R, PageR
from app.module.collection.service import CollService


@router(prefix='/coll', tags=["coll"])
class CollRouter(RouterBase):
    coll_service: CollService

    @post(
        '/submit',
        summary="提交 URL 采集",
        request_model=SubmitUrlRequest,
        response_model=R[dict],
    )
    async def submit_url(self, body: SubmitUrlRequest):
        success, result = self.coll_service.submit_url(body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/list',
        summary="采集列表",
        response_model=PageR[CollectionItemResponse],
    )
    async def list_items(self, page: int = 1, size: int = 20):
        success, result = self.coll_service.list_items(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/{item_id}',
        summary="采集详情",
        response_model=R[CollectionItemResponse],
    )
    async def get_item(self, item_id: str):
        success, result = self.coll_service.get_item(item_id)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/{item_id}',
        summary="删除采集",
        response_model=R[str],
    )
    async def delete_item(self, item_id: str):
        success, result = self.coll_service.delete_item(item_id)
        return R.ok(result) if success else R.fail(result)

    @post(
        '/{item_id}/import/{kb_id}',
        summary="导入到知识库",
        response_model=R[ImportToKbResponse],
    )
    async def import_to_kb(self, item_id: str, kb_id: str):
        success, result = self.coll_service.import_to_kb(item_id, kb_id)
        return R.ok(result) if success else R.fail(result)
