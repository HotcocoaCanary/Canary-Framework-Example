import uuid
from datetime import datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from canary_framework import after_config, after_init
from canary_framework.decorators import service
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.config import AppConfig
from app.module.db.models import KnowledgeBase


@service()
class KnowledgeBaseRepository:
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
        return "kb_" + uuid.uuid4().hex  # 32 位字符串

    def create_knowledge_base(self, name: str, created_by: str, description: str = "",
                              permission: str = "private") -> KnowledgeBase:
        with self.get_session() as session:
            kb = KnowledgeBase(
                id=self.generate_id(),
                name=name,
                description=description,
                permission=permission,
                created_by=created_by,
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                updated_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            session.add(kb)
            session.commit()
            session.refresh(kb)
            return kb

    def get_knowledge_base(self, kb_id: str) -> type[KnowledgeBase] | None:
        with self.get_session() as session:
            return session.get(KnowledgeBase, kb_id)

    def update_knowledge_base(self, kb_id: str, **kwargs) -> type[KnowledgeBase] | None:
        with self.get_session() as session:
            kb = session.get(KnowledgeBase, kb_id)
            if not kb:
                return None
            for key, value in kwargs.items():
                if hasattr(kb, key) and key not in ["id", "created_at", "created_by"]:
                    setattr(kb, key, value)
            kb.updated_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            session.add(kb)
            session.commit()
            session.refresh(kb)
            return kb

    def delete_knowledge_base(self, kb_id: str) -> bool:
        with self.get_session() as session:
            kb = session.get(KnowledgeBase, kb_id)
            if not kb:
                return False
            session.delete(kb)
            session.commit()
            return True

    def list_knowledge_bases(self, created_by: str, skip: int = 0, limit: int = 100) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KnowledgeBase).where(KnowledgeBase.created_by == created_by).offset(skip).limit(limit)
            return session.exec(statement).all()
