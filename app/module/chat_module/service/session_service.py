import logging
import uuid

from canary_framework import service, on_init, Context
from canary_framework.web.fastapi import web
from fastapi import HTTPException

from app.common.response import R
from app.common.types import UserContext
from app.module.chat_module.router.session_router import SessionRouter
from app.module.chat_module.schema import SessionResponse, MessageResponse
from app.module.db_module.models import Session
from app.module.db_module.service import DBService

logger = logging.getLogger(__name__)


@web(routers=[SessionRouter])
@service(name="SessionService", deps=[DBService])
class SessionService:
    @on_init
    def init(self, ctx: Context):
        pass

    async def list_sessions(self, user: UserContext, current: int = 1, size: int = 20) -> R[dict]:
        async with self.db_service.transaction() as session:
            session_repo = self.db_service.session_repo(session)
            sessions, total = await session_repo.list_by_user(user.user_id, current, size)

            records = [
                SessionResponse(
                    id=s.id,
                    title=s.name,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
                for s in sessions
            ]
            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in records],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def get_messages(self, session_id: str, user: UserContext, current: int = 1, size: int = 50) -> R[dict]:
        async with self.db_service.transaction() as session:
            session_repo = self.db_service.session_repo(session)
            message_repo = self.db_service.message_repo(session)

            sess = await session_repo.get_by_id(session_id)
            if not sess:
                raise HTTPException(status_code=404, detail="会话不存在")
            if sess.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")

            messages, total = await message_repo.list_by_session(session_id, current, size)
            records = [
                MessageResponse(
                    role=m.role,
                    content=m.content,
                    sources=m.sources or [],
                )
                for m in messages
            ]
            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in records],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def delete_session(self, session_id: str, user: UserContext) -> R[None]:
        async with self.db_service.transaction() as session:
            session_repo = self.db_service.session_repo(session)
            message_repo = self.db_service.message_repo(session)

            sess = await session_repo.get_by_id(session_id)
            if not sess:
                raise HTTPException(status_code=404, detail="会话不存在")
            if sess.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")

            await message_repo.delete_by_session(session_id)
            await session_repo.delete(session_id)

            logger.info(f"Session deleted: id={session_id}")
            return R.ok(msg="删除成功")

    async def create_session(self, user: UserContext, title: str = None) -> str:
        async with self.db_service.transaction() as session:
            session_repo = self.db_service.session_repo(session)
            session_id = f"sess_{uuid.uuid4().hex[:20]}"
            sess = Session(
                id=session_id,
                user_id=user.user_id,
                name=title or "",
            )
            await session_repo.create(sess)
            return session_id
