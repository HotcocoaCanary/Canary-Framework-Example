import uuid
from datetime import datetime
from typing import Any, Sequence, Optional

from canary_framework import cocoa, on_start
from sqlalchemy import create_engine, and_
from sqlmodel import Session, select

from app.module.db.models import KbFile
from config import AppConfig


@cocoa(deps=[AppConfig])
class KBFileRepository:

    @on_start
    async def setup(self) -> None:
        self.engine = create_engine(self.app_config.database_url, echo=True)

    def get_session(self):
        return Session(self.engine)

    @staticmethod
    def generate_id() -> str:
        return "file_" + uuid.uuid4().hex[:20]

    def create_kb_file(self, kb_id: str, name: str, created_by: str, file_type: Optional[str] = None,
                       file_size: Optional[int] = None, parent_path: str = "/",
                       oss_url: Optional[str] = None, status: str = "pending",
                       parsed_text: Optional[str] = None, error_msg: Optional[str] = None) -> KbFile:
        with self.get_session() as session:
            file = KbFile(
                id=self.generate_id(),
                kb_id=kb_id,
                name=name,
                file_type=file_type,
                file_size=file_size,
                parent_path=parent_path,
                oss_url=oss_url,
                status=status,
                parsed_text=parsed_text,
                error_msg=error_msg,
                created_by=created_by,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(file)
            session.commit()
            session.refresh(file)
            return file

    def get_kb_file(self, file_id: str) -> type[KbFile] | None:
        with self.get_session() as session:
            return session.get(KbFile, file_id)

    def get_kb_file_by_path(self, kb_id: str, parent_path: str, name: str) -> type[KbFile] | None:
        with self.get_session() as session:
            statement = select(KbFile).where(
                and_(
                    KbFile.kb_id == kb_id,
                    KbFile.parent_path == parent_path,
                    KbFile.name == name
                )
            )
            return session.exec(statement).first()

    def get_unique_name(self, kb_id: str, parent_path: str, name: str) -> str:
        with self.get_session() as session:
            base_name = name
            counter = 1
            while True:
                statement = select(KbFile).where(
                    and_(
                        KbFile.kb_id == kb_id,
                        KbFile.parent_path == parent_path,
                        KbFile.name == name
                    )
                )
                if not session.exec(statement).first():
                    return name
                name = f"{base_name}_{counter}"
                counter += 1

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

    def delete_kb_file_by_path(self, kb_id: str, parent_path: str, name: str) -> bool:
        with self.get_session() as session:
            statement = select(KbFile).where(
                and_(
                    KbFile.kb_id == kb_id,
                    KbFile.parent_path == parent_path,
                    KbFile.name == name
                )
            )
            file = session.exec(statement).first()
            if not file:
                return False
            session.delete(file)
            session.commit()
            return True

    def list_files_by_kb(self, kb_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KbFile).where(KbFile.kb_id == kb_id)
            return session.exec(statement).all()

    def list_children(self, kb_id: str, parent_path: str, skip: int = 0, limit: int = 100) -> tuple[Sequence[Any], int]:
        with self.get_session() as session:
            statement = select(KbFile).where(
                and_(
                    KbFile.kb_id == kb_id,
                    KbFile.parent_path == parent_path
                )
            )
            count_statement = select(KbFile).where(
                and_(
                    KbFile.kb_id == kb_id,
                    KbFile.parent_path == parent_path
                )
            )
            total = len(session.exec(count_statement).all())
            statement = statement.order_by(KbFile.updated_at.desc()).offset(skip).limit(limit)
            return session.exec(statement).all(), total

    def delete_files_by_kb(self, kb_id: str) -> int:
        with self.get_session() as session:
            statement = select(KbFile).where(KbFile.kb_id == kb_id)
            files = session.exec(statement).all()
            count = 0
            for file in files:
                session.delete(file)
                count += 1
            session.commit()
            return count

    def total_size_by_owner(self, created_by: str) -> int:
        with self.get_session() as session:
            statement = select(KbFile).where(KbFile.created_by == created_by)
            files = session.exec(statement).all()
            total = 0
            for file in files:
                if file.file_size:
                    total += file.file_size
            return total
