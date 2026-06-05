from canary_framework import router, get, post, delete, patch
from canary_framework.core.router import RouterBase

from app.common.response import R, PageR
from app.module.kb.schema import CreateKbRequest, KbResponse, UpdateKbRequest, ShareLinkResponse, StorageResponse
from app.module.kb.service import KbService


@router(prefix='/kb', tags=["kb"])
class KBRouter(RouterBase):
    kb_service: KbService

    @post(
        '/',
        summary="创建知识库",
        description="传入必要参数，为当前用户创建知识库",
        request_model=CreateKbRequest,
        response_model=R[KbResponse],
    )
    async def create(self, body: CreateKbRequest):
        success, result = self.kb_service.create_kb(body)
        return R.ok(result) if success else R.fail(result)

    @get(
        '/',
        summary="查询知识库列表",
        description="传入分页参数，获取知识库列表，已经过滤当前用户权限",
        response_model=PageR[KbResponse],
    )
    async def list(self, page: int = 1, size: int = 20):
        success, result = self.kb_service.list_user_kbs(page=page, size=size)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        '/public',
        summary="公开知识库列表",
        description="获取所有公开的知识库列表",
        response_model=PageR[KbResponse],
    )
    async def list_public(self, page: int = 1, size: int = 20, keyword: str | None = None):
        success, result = self.kb_service.list_public_kbs(keyword=keyword, page=page, size=size)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        '/storage',
        summary="用户空间统计",
        description="统计当前用户作为创建者的所有知识库文件大小",
        response_model=R[StorageResponse],
    )
    async def get_storage(self):
        success, result = self.kb_service.get_user_storage()
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        '/shared/{share_token}',
        summary="通过分享链接查看知识库",
        response_model=R[KbResponse],
    )
    async def get_shared(self, share_token: str):
        success, result = self.kb_service.get_shared_kb(share_token)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        '/{kb_id}',
        summary="知识库详情",
        response_model=R[KbResponse],
    )
    async def get(self, kb_id: str):
        success, result = self.kb_service.get_kb(kb_id)
        if success:
            return R.ok(result)
        return R.fail(result)

    @patch(
        '/{kb_id}',
        summary="更新知识库",
        description="根据kb_id更新知识库",
        request_model=UpdateKbRequest,
        response_model=R[KbResponse],
    )
    async def update(self, kb_id: str, body: UpdateKbRequest):
        success, result = self.kb_service.update_kb(kb_id, body)
        if success:
            return R.ok(result)
        return R.fail(result)

    @delete(
        '/{kb_id}',
        summary="删除知识库",
        description="根据kb_id删除知识库",
        response_model=R[str],
    )
    async def delete(self, kb_id: str):
        success, result = self.kb_service.delete_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @post(
        '/{kb_id}/share-link',
        summary="生成分享链接",
        response_model=R[ShareLinkResponse],
    )
    async def create_share_link(self, kb_id: str):
        success, result = self.kb_service.create_share_link(kb_id)
        if success:
            return R.ok(result)
        return R.fail(result)

    @post(
        '/{kb_id}/join',
        summary="加入知识库",
        response_model=R[str],
    )
    async def join(self, kb_id: str):
        success, result = self.kb_service.join_kb(kb_id)
        return R.ok(result) if success else R.fail(result)
