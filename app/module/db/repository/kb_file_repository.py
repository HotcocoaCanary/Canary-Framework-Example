import uuid
from datetime import datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from canary_framework import after_config, after_init
from canary_framework.decorators import service
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.config import AppConfig
from app.module.db.models import KbFile


@service()
class KBFileRepository:
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
        return "kf_" + uuid.uuid4().hex  # 32 位字符串

    def create_kb_file(self, kb_id: str, name: str, created_by: str, file_type: str = None, file_size: int = None,
                       parent_path: str = "", oss_url: str = "") -> KbFile:
        with self.get_session() as session:
            file = KbFile(
                id=self.generate_id(),
                kb_id=kb_id,
                name=name,
                file_type=file_type,
                file_size=file_size,
                parent_path=parent_path,
                oss_url=oss_url,
                status="pending",  # 自定义初始状态
                created_by=created_by,
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                updated_at=datetime.now(ZoneInfo("Asia/Shanghai"))
            )
            session.add(file)
            session.commit()
            session.refresh(file)
            return file

    def get_kb_file(self, file_id: str) -> type[KbFile] | None:
        with self.get_session() as session:
            return session.get(KbFile, file_id)

    def update_kb_file(self, file_id: str, **kwargs) -> type[KbFile] | None:
        with self.get_session() as session:
            file = session.get(KbFile, file_id)
            if not file:
                return None
            for key, value in kwargs.items():
                if hasattr(file, key) and key not in ["id", "kb_id", "created_at", "created_by"]:
                    setattr(file, key, value)
            file.updated_at = datetime.utcnow()
            session.add(file)
            session.commit()
            session.refresh(file)
            return file

    def delete_kb_file(self, file_id: str) -> bool:
        with self.get_session() as session:
            file = session.get(KbFile, file_id)
            if not file:
                return False
            session.delete(file)
            session.commit()
            return True

    def list_files_by_kb(self, kb_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KbFile).where(KbFile.kb_id == kb_id)
            return session.exec(statement).all()
