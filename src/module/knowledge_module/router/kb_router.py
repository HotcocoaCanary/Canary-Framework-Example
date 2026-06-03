from canary_framework import router, get, post, put, delete

from app import get_current_user
from src.common.pagination import parse_pagination
from src.module.knowledge_module.schema import CreateKbRequest, UpdateKbRequest
from src.module.knowledge_module.service.kb_service import KbService
from app import AuthService


@router(name="kb_api", prefix="/api/v1/knowledge-bases", deps=[KbService, AuthService])
class KbRouter:
    kb_service: KbService
    auth_service: AuthService

    @post("/", request_model=CreateKbRequest, tags=["知识库"], summary="创建知识库",
          description="创建一个新的知识库，当前用户自动成为 owner")
    async def create(self, request, req: CreateKbRequest):
        user = await get_current_user(request, self.auth_service)
        return await self.kb_service.create_kb(user, req)

    @get("/", tags=["知识库"], summary="我的知识库列表", description="获取当前用户创建或加入的所有知识库")
    async def list_kbs(self, request):
        user = await get_current_user(request, self.auth_service)
        current, size = parse_pagination(request)
        return await self.kb_service.list_user_kbs(user, current, size)

    @get("/public", tags=["知识库"], summary="公开知识库列表", description="无需认证，浏览所有公开知识库")
    async def list_public(self, request):
        current, size = parse_pagination(request)
        keyword = request.query_params.get("keyword")
        return await self.kb_service.list_public_kbs(current, size, keyword)

    @get("/shared/{share_token}", tags=["知识库"], summary="通过分享链接查看知识库")
    async def get_shared(self, request):
        share_token = request.path_params["share_token"]
        return await self.kb_service.get_shared_kb(share_token)

    @get("/me/storage", tags=["知识库"], summary="用户空间统计",
         description="统计当前用户作为创建者的所有知识库文件大小")
    async def get_storage(self, request):
        user = await get_current_user(request, self.auth_service)
        return await self.kb_service.get_user_storage(user)

    @get("/{kb_id}", tags=["知识库"], summary="知识库详情")
    async def view_kb(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        return await self.kb_service.get_kb(kb_id, user)

    @put("/{kb_id}", request_model=UpdateKbRequest, tags=["知识库"], summary="更新知识库")
    async def update(self, request, req: UpdateKbRequest):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        return await self.kb_service.update_kb(kb_id, user, req)

    @delete("/{kb_id}", tags=["知识库"], summary="删除知识库", description="仅创建者可操作，级联删除所有文件、分块和成员")
    async def delete(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        return await self.kb_service.delete_kb(kb_id, user)

    @post("/{kb_id}/share-link", tags=["知识库"], summary="生成分享链接",
          description="仅 shared 权限知识库且创建者可操作")
    async def create_share_link(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        return await self.kb_service.create_share_link(kb_id, user)

    @post("/{kb_id}/join", tags=["知识库"], summary="加入知识库")
    async def join(self, request):
        user = await get_current_user(request, self.auth_service)
        kb_id = request.path_params["kb_id"]
        return await self.kb_service.join_kb(kb_id, user)
