from canary_framework import router, get, delete

from app import get_current_user
from src.common.pagination import parse_pagination
from src.module.chat_module.service.session_service import SessionService
from app import AuthService


@router(name="session_api", prefix="/api/v1/sessions", deps=[SessionService, AuthService])
class SessionRouter:
    session_service: SessionService
    auth_service: AuthService

    @get("/", tags=["会话"], summary="会话列表", description="获取当前用户的所有会话，按更新时间倒序")
    async def list_sessions(self, request):
        user = await get_current_user(request, self.auth_service)
        current, size = parse_pagination(request)
        return await self.session_service.list_sessions(user, current, size)

    @get("/{session_id}/messages", tags=["会话"], summary="历史消息", description="获取指定会话的消息记录，按时间正序")
    async def get_messages(self, request):
        user = await get_current_user(request, self.auth_service)
        session_id = request.path_params["session_id"]
        current, size = parse_pagination(request, default_size=50)
        return await self.session_service.get_messages(session_id, user, current, size)

    @delete("/{session_id}", tags=["会话"], summary="删除会话", description="删除会话及其所有消息")
    async def delete_session(self, request):
        user = await get_current_user(request, self.auth_service)
        session_id = request.path_params["session_id"]
        return await self.session_service.delete_session(session_id, user)
