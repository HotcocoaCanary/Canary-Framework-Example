from fastapi import Depends, Query

from app.common.depends import get_current_user
from canary_framework import Context
from canary_framework.web.fastapi import router, get, delete


@router(prefix="/api/v1/sessions")
class SessionRouter:
    def __init__(self, ctx: Context):
        from app.module.chat_module.service.session_service import SessionService
        self.svc = ctx.resolve(SessionService)

    @get("/", tags=["会话"], summary="会话列表", description="获取当前用户的所有会话，按更新时间倒序")
    async def list_sessions(
            self,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            user=Depends(get_current_user),
    ):
        return await self.svc.list_sessions(user, current, size)

    @get("/{session_id}/messages", tags=["会话"], summary="历史消息", description="获取指定会话的消息记录，按时间正序")
    async def get_messages(
            self,
            session_id: str,
            current: int = Query(1, description="页码"),
            size: int = Query(50, description="每页大小"),
            user=Depends(get_current_user),
    ):
        return await self.svc.get_messages(session_id, user, current, size)

    @delete("/{session_id}", tags=["会话"], summary="删除会话", description="删除会话及其所有消息")
    async def delete_session(self, session_id: str, user=Depends(get_current_user)):
        return await self.svc.delete_session(session_id, user)
