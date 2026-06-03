import uuid
from datetime import datetime
from typing import Optional, Any, Sequence

from canary_framework import after_config, after_init
from canary_framework.decorators import service
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.config import AppConfig
from app.module.db.models import Message


@service()
class MessageRepository:
    config: AppConfig

    def __init__(self):
        self.engine = None
        self.session = None
        self.database_url = None

    @after_config
    def after_config(self):
        self.database_url = self.config.database_url

    @after_init
    def after_init(self):
        self.engine = create_engine(self.database_url, echo=True)

    def get_session(self):
        return Session(self.engine)

    @staticmethod
    def generate_id() -> str:
        return "msg_" + uuid.uuid4().hex

    def create_message(self, session_id: str, role: str, content: str,
                       sources: Optional[list[dict]] = None) -> Message:
        with self.get_session() as session:
            message = Message(
                id=self.generate_id(),
                session_id=session_id,
                role=role,
                content=content,
                sources=sources,
                created_at=datetime.utcnow(),
            )
            session.add(message)
            session.commit()
            session.refresh(message)
            return message

    def get_message(self, message_id: str) -> type[Message] | None:
        with self.get_session() as session:
            return session.get(Message, message_id)

    def update_message(self, message_id: str, **kwargs) -> type[Message] | None:
        with self.get_session() as session:
            message = session.get(Message, message_id)
            if not message:
                return None
            for key, value in kwargs.items():
                if hasattr(message, key) and key not in ["id", "session_id", "created_at"]:
                    setattr(message, key, value)
            session.add(message)
            session.commit()
            session.refresh(message)
            return message

    def delete_message(self, message_id: str) -> bool:
        with self.get_session() as session:
            message = session.get(Message, message_id)
            if not message:
                return False
            session.delete(message)
            session.commit()
            return True

    def list_messages_by_session(self, session_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
            return session.exec(statement).all()

    def delete_messages_by_session(self, session_id: str) -> int:
        with self.get_session() as session:
            statement = select(Message).where(Message.session_id == session_id)
            messages = session.exec(statement).all()
            count = 0
            for message in messages:
                session.delete(message)
                count += 1
            session.commit()
            return count