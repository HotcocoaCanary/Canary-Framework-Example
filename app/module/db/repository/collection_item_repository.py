import uuid
from datetime import datetime
from typing import Optional, Any, Sequence

from canary_framework import after_config, after_init
from canary_framework.decorators import service
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.config import AppConfig
from app.module.db.models import CollectionItem


@service()
class CollectionItemRepository:
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
        return "ci_" + uuid.uuid4().hex

    def create_item(self, user_id: str, url: str, title: Optional[str] = None,
                    content: Optional[str] = None, status: str = "pending") -> CollectionItem:
        with self.get_session() as session:
            item = CollectionItem(
                id=self.generate_id(),
                user_id=user_id,
                url=url,
                title=title,
                content=content,
                status=status,
                is_imported=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def get_item(self, item_id: str) -> type[CollectionItem] | None:
        with self.get_session() as session:
            return session.get(CollectionItem, item_id)

    def update_item(self, item_id: str, **kwargs) -> type[CollectionItem] | None:
        with self.get_session() as session:
            item = session.get(CollectionItem, item_id)
            if not item:
                return None
            for key, value in kwargs.items():
                if hasattr(item, key) and key not in ["id", "user_id", "created_at"]:
                    setattr(item, key, value)
            item.updated_at = datetime.utcnow()
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def delete_item(self, item_id: str) -> bool:
        with self.get_session() as session:
            item = session.get(CollectionItem, item_id)
            if not item:
                return False
            session.delete(item)
            session.commit()
            return True

    def list_items_by_user(self, user_id: str, status: Optional[str] = None,
                           skip: int = 0, limit: int = 100) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(CollectionItem).where(CollectionItem.user_id == user_id)
            if status:
                statement = statement.where(CollectionItem.status == status)
            statement = statement.offset(skip).limit(limit).order_by(CollectionItem.created_at.desc())
            return session.exec(statement).all()

    def list_pending_items(self, user_id: str, limit: int = 100) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(CollectionItem).where(
                CollectionItem.user_id == user_id,
                CollectionItem.status == "pending"
            ).limit(limit)
            return session.exec(statement).all()