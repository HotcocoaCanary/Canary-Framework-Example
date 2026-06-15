import uuid
from datetime import datetime
from typing import Optional, Any, Sequence

from canary_framework import service
from canary_framework.core.service import ServiceBase
from sqlalchemy import create_engine
from sqlmodel import Session as SqlSession, select

from app.module.db.models import Session


@service()
class SessionRepository(ServiceBase):

    def init(self):
        super().init()
        self.engine = create_engine(self.config.database_url, echo=True)

    def get_session(self):
        return SqlSession(self.engine)

    @staticmethod
    def generate_id() -> str:
        return "ss_" + uuid.uuid4().hex

    def create_session(self, user_id: str, name: Optional[str] = None) -> Session:
        with self.get_session() as session:
            session_obj = Session(
                id=self.generate_id(),
                user_id=user_id,
                name=name,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(session_obj)
            session.commit()
            session.refresh(session_obj)
            return session_obj

    def get_session_by_id(self, session_id: str) -> type[Session] | None:
        with self.get_session() as session:
            return session.get(Session, session_id)

    def update_session(self, session_id: str, **kwargs) -> type[Session] | None:
        with self.get_session() as session:
            session_obj = session.get(Session, session_id)
            if not session_obj:
                return None
            for key, value in kwargs.items():
                if hasattr(session_obj, key) and key not in ["id", "user_id", "created_at"]:
                    setattr(session_obj, key, value)
            session_obj.updated_at = datetime.utcnow()
            session.add(session_obj)
            session.commit()
            session.refresh(session_obj)
            return session_obj

    def delete_session(self, session_id: str) -> bool:
        with self.get_session() as session:
            session_obj = session.get(Session, session_id)
            if not session_obj:
                return False
            session.delete(session_obj)
            session.commit()
            return True

    def list_sessions_by_user(self, user_id: str, skip: int = 0, limit: int = 100) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(Session).where(Session.user_id == user_id).offset(skip).limit(limit).order_by(
                Session.updated_at.desc())
            return session.exec(statement).all()
