from canary_framework import post, get, delete
from canary_framework.decorators import router

from app.module.collection.schema import SubmitUrlRequest, CollectionItemResponse, ImportToKbResponse
from app.common.response import R, PageR
from app.module.collection.service import CollService


@router(prefix='/coll', tags=["coll"])
class CollRouter:
    coll_service: CollService

    @post(
        path='/submit',
        summary="提交 URL 采集",
        request_model=SubmitUrlRequest,
        response_model=R[dict],
        responses={
            "200": {"model": R[dict]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def submit_url(self, request: SubmitUrlRequest):
        success, result = self.coll_service.submit_url(request)
        return R.ok(result) if success else R.fail(result)

    @get(
        path='/list',
        summary="采集列表",
        response_model=PageR[CollectionItemResponse],
        responses={
            "200": {"model": PageR[CollectionItemResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def list_items(self, page: int = 1, size: int = 20):
        success, result = self.coll_service.list_items(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @get(
        path='/{item_id}',
        summary="采集详情",
        response_model=R[CollectionItemResponse],
        responses={
            "200": {"model": R[CollectionItemResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def get_item(self, item_id: str):
        success, result = self.coll_service.get_item(item_id)
        return R.ok(result) if success else R.fail(result)

    @delete(
        path='/{item_id}',
        summary="删除采集",
        response_model=R[str],
        responses={
            "200": {"model": R[str]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def delete_item(self, item_id: str):
        success, result = self.coll_service.delete_item(item_id)
        return R.ok(result) if success else R.fail(result)

    @post(
        path='/{item_id}/import/{kb_id}',
        summary="导入到知识库",
        response_model=R[ImportToKbResponse],
        responses={
            "200": {"model": R[ImportToKbResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def import_to_kb(self, item_id: str, kb_id: str):
        success, result = self.coll_service.import_to_kb(item_id, kb_id)
        return R.ok(result) if success else R.fail(result)
