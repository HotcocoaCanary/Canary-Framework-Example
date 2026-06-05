from canary_framework import router, get, post, delete
from canary_framework.core.router import RouterBase

from app.module.collection.schema import SubmitUrlRequest, CollectionItemResponse
from app.common.response import R, PageR
from app.module.collection.service import CollService


@router(prefix='/coll', tags=["coll"])
class CollRouter(RouterBase):
    coll_service: CollService

    @post(
        '/create',
        summary="创建采集任务",
        request_model=SubmitUrlRequest,
        response_model=R[dict],
    )
    async def create(self, body: SubmitUrlRequest):
        success, result = self.coll_service.submit_url(body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/list?page={page}&size={size}',
        summary="采集列表",
        response_model=PageR[CollectionItemResponse],
    )
    async def list_items(self, page: int = 1, size: int = 20):
        success, result = self.coll_service.list_items(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/{coll_id}/delete',
        summary="删除采集",
        response_model=R[str],
    )
    async def delete_item(self, coll_id: str):
        success, result = self.coll_service.delete_item(coll_id)
        return R.ok(result) if success else R.fail(result)
