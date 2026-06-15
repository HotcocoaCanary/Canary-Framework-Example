from canary_framework import service
from canary_framework.core.router import Router
from canary_framework.core.service import ServiceBase

from app.common.response import R, PageR
from app.module.kb.schema import CreateKbRequest, KbResponse, UpdateKbRequest, ShareLinkResponse
from app.module.kb.service import KbService


@service()
class KBRouter(ServiceBase):
    router = Router(prefix='/kb', tags=["kb"])
    kb_service: KbService

    @router.post(
        '/create',
        summary="创建知识库",
        request_model=CreateKbRequest,
        response_model=R[KbResponse],
    )
    async def create(self, body: CreateKbRequest):
        success, result = self.kb_service.create_kb(body)
        return R.ok(result) if success else R.fail(result)

    @router.get(
        '/list?page={page}&size={size}',
        summary="知识库列表",
        response_model=PageR[KbResponse],
    )
    async def list(self, page: int = 1, size: int = 20):
        success, result = self.kb_service.list_user_kbs(page=page, size=size)
        return R.ok(result) if success else R.fail(result)

    @router.delete(
        '/{kb_id}/dalete',
        summary="删除知识库",
        response_model=R[str],
    )
    async def delete(self, kb_id: str):
        success, result = self.kb_service.delete_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @router.patch(
        '/{kb_id}/update',
        summary="更新知识库",
        request_model=UpdateKbRequest,
        response_model=R[KbResponse],
    )
    async def update(self, kb_id: str, body: UpdateKbRequest):
        success, result = self.kb_service.update_kb(kb_id, body)
        return R.ok(result) if success else R.fail(result)

    @router.get(
        '/{kb_id}/join',
        summary="加入知识库",
        response_model=R[str],
    )
    async def join(self, kb_id: str):
        success, result = self.kb_service.join_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @router.get(
        '/{kb_id}/shared',
        summary="获取分享链接",
        response_model=R[ShareLinkResponse],
    )
    async def shared(self, kb_id: str):
        success, result = self.kb_service.create_share_link(kb_id)
        return R.ok(result) if success else R.fail(result)

    @router.post(
        '/public/list?page={page}&size={size}',
        summary="公开知识库列表",
        response_model=PageR[KbResponse],
    )
    async def list_public(self, page: int = 1, size: int = 20, keyword: str | None = None):
        success, result = self.kb_service.list_public_kbs(keyword=keyword, page=page, size=size)
        return R.ok(result) if success else R.fail(result)
