from typing import Any

from canary_framework.web import delete, get, post

from app.common.response import R, PageR
from app.module.collection.schema import SubmitUrlRequest, CollectionItemResponse
from app.module.collection.service import CollService


class CollRouter:
    coll_service: CollService

    @post(
        '/coll/create',
    )
    async def create(self, body: SubmitUrlRequest) -> R[None] | Any:
        success, result = self.coll_service.submit_url(body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/coll/list',
    )
    async def list_items(self, page: int = 1, size: int = 20) -> R[None] | Any:
        success, result = self.coll_service.list_items(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/coll/{coll_id}/delete',
    )
    async def delete_item(self, coll_id: str) -> R[str] | R[None]:
        success, result = self.coll_service.delete_item(coll_id)
        return R.ok(result) if success else R.fail(result)
