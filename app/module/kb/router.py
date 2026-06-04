from canary_framework import post, get, delete, patch
from canary_framework.decorators import router

from app.common.response import R, PageR
from app.module.kb.schema import CreateKbRequest, KbResponse, UpdateKbRequest, ShareLinkResponse, StorageResponse
from app.module.kb.service import KbService


@router(prefix='/kb', tags=["kb"])
class KBRouter:
    kb_service: KbService

    @post(
        path='/',
        summary="创建知识库",
        description="传入必要参数，为当前用户创建知识库",
        request_model=CreateKbRequest,
        response_model=R[KbResponse],
        responses={
            "200": {"model": R[KbResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def create(self, request: CreateKbRequest):
        success, result = self.kb_service.create_kb(request)
        return R.ok(result) if success else R.fail(result)

    @get(
        path='/',
        summary="查询知识库列表",
        description="传入分页参数，获取知识库列表，已经过滤当前用户权限",
        response_model=PageR[KbResponse],
        responses={
            "200": {"model": PageR[KbResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def list(self, page: int = 1, size: int = 20):
        success, result = self.kb_service.list_user_kbs(page=page, size=size)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        path='/public',
        summary="公开知识库列表",
        description="获取所有公开的知识库列表",
        response_model=PageR[KbResponse],
        responses={
            "200": {"model": PageR[KbResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def list_public(self, page: int = 1, size: int = 20, keyword: str | None = None):
        success, result = self.kb_service.list_public_kbs(keyword=keyword, page=page, size=size)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        path='/storage',
        summary="用户空间统计",
        description="统计当前用户作为创建者的所有知识库文件大小",
        response_model=R[StorageResponse],
        responses={
            "200": {"model": R[StorageResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def get_storage(self):
        success, result = self.kb_service.get_user_storage()
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        path='/shared/{share_token}',
        summary="通过分享链接查看知识库",
        response_model=R[KbResponse],
        responses={
            "200": {"model": R[KbResponse]},
            "400": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def get_shared(self, share_token: str):
        success, result = self.kb_service.get_shared_kb(share_token)
        if success:
            return R.ok(result)
        return R.fail(result)

    @get(
        path='/{kb_id}',
        summary="知识库详情",
        response_model=R[KbResponse],
        responses={
            "200": {"model": R[KbResponse]},
            "400": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def get(self, kb_id: str):
        success, result = self.kb_service.get_kb(kb_id)
        if success:
            return R.ok(result)
        return R.fail(result)

    @patch(
        path='/{kb_id}',
        summary="更新知识库",
        description="根据kb_id更新知识库",
        request_model=UpdateKbRequest,
        response_model=R[KbResponse],
        responses={
            "200": {"model": R[KbResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def update(self, kb_id: str, request: UpdateKbRequest):
        success, result = self.kb_service.update_kb(kb_id, request)
        if success:
            return R.ok(result)
        return R.fail(result)

    @delete(
        path='/{kb_id}',
        summary="删除知识库",
        description="根据kb_id删除知识库",
        response_model=R[str],
        responses={
            "200": {"model": R[str]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def delete(self, kb_id: str):
        success, result = self.kb_service.delete_kb(kb_id)
        return R.ok(result) if success else R.fail(result)

    @post(
        path='/{kb_id}/share-link',
        summary="生成分享链接",
        response_model=R[ShareLinkResponse],
        responses={
            "200": {"model": R[ShareLinkResponse]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def create_share_link(self, kb_id: str):
        success, result = self.kb_service.create_share_link(kb_id)
        if success:
            return R.ok(result)
        return R.fail(result)

    @post(
        path='/{kb_id}/join',
        summary="加入知识库",
        response_model=R[str],
        responses={
            "200": {"model": R[str]},
            "400": {"model": R[str]},
            "401": {"model": R[str]},
            "404": {"model": R[str]},
            "500": {"model": R[str]},
        }
    )
    def join(self, kb_id: str):
        success, result = self.kb_service.join_kb(kb_id)
        return R.ok(result) if success else R.fail(result)
