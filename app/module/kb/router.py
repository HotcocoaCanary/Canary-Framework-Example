from canary_framework.web import delete, get, patch, post

from app.common.response import R, PageR
from app.module.kb.schema import CreateKbRequest, KbResponse, UpdateKbRequest, ShareLinkResponse
from app.module.kb.service import KbService


class KBRouter:
    kb_service: KbService

    @post(
        '/kb/create',
    )
    async def create(self, body: CreateKbRequest) -> R[KbResponse]:
        success, result = self.kb_service.create_kb(body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/kb/list',
    )
    async def list(self, page: int = 1, size: int = 20) -> PageR[KbResponse]:
        success, result = self.kb_service.list_user_kbs(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @delete(
        '/kb/{kb_id}/delete',
    )
    async def delete(self, kb_id: str) -> R[str]:
        success, result = self.kb_service.delete_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @patch(
        '/kb/{kb_id}/update',
    )
    async def update(self, kb_id: str, body: UpdateKbRequest) -> R[KbResponse]:
        success, result = self.kb_service.update_kb(kb_id, body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/kb/{kb_id}/join',
    )
    async def join(self, kb_id: str) -> R[str]:
        success, result = self.kb_service.join_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/kb/{kb_id}/shared',
    )
    async def shared(self, kb_id: str) -> R[ShareLinkResponse]:
        success, result = self.kb_service.create_share_link(kb_id)
        return R.ok(result) if success else R.fail(result)

    @post(
        '/kb/public/list',
    )
    async def list_public(self, page: int = 1, size: int = 20, keyword: str | None = None) -> PageR[KbResponse]:
        success, result = self.kb_service.list_public_kbs(keyword=keyword, page=page, size=size)
        return R.ok(result) if success else R.fail(result)
