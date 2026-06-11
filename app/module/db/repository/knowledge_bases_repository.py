import uuid
from datetime import datetime
from typing import Any, Sequence, Optional

from canary_framework import service, after_init
from canary_framework.core.service import ServiceBase
from sqlalchemy import create_engine, or_
from sqlmodel import Session, select

from config import AppConfig
from app.module.db.models import KnowledgeBase


@service()
class KnowledgeBaseRepository(ServiceBase):
    config: AppConfig

    @after_init
    async def after_init(self):
        self.engine = create_engine(self.config.database_url, echo=True)

    def get_session(self):
        return Session(self.engine)

    @staticmethod
    def generate_id() -> str:
        return "kb_" + uuid.uuid4().hex[:20]

    def create_knowledge_base(self, name: str, created_by: str, description: Optional[str] = None,
                              permission: str = "private") -> KnowledgeBase:
        with self.get_session() as session:
            kb = KnowledgeBase(
                id=self.generate_id(),
                name=name,
                description=description,
                permission=permission,
                created_by=created_by,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
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
            kb.updated_at = datetime.utcnow()
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
            statement = select(KnowledgeBase).where(KnowledgeBase.created_by == created_by).order_by(KnowledgeBase.updated_at.desc()).offset(skip).limit(limit)
            return session.exec(statement).all()

    def list_public_knowledge_bases(self, keyword: Optional[str] = None, skip: int = 0, limit: int = 100) -> tuple[Sequence[Any], int]:
        with self.get_session() as session:
            statement = select(KnowledgeBase).where(KnowledgeBase.permission == "shared")
            if keyword:
                statement = statement.where(or_(KnowledgeBase.name.contains(keyword), KnowledgeBase.description.contains(keyword)))
            
            count_statement = select(KnowledgeBase).where(KnowledgeBase.permission == "shared")
            if keyword:
                count_statement = count_statement.where(or_(KnowledgeBase.name.contains(keyword), KnowledgeBase.description.contains(keyword)))
            
            total = len(session.exec(count_statement).all())
            statement = statement.order_by(KnowledgeBase.updated_at.desc()).offset(skip).limit(limit)
            return session.exec(statement).all(), total

    def get_knowledge_base_by_share_token(self, share_token: str) -> type[KnowledgeBase] | None:
        with self.get_session() as session:
            statement = select(KnowledgeBase).where(KnowledgeBase.share_token == share_token)
            return session.exec(statement).first()
