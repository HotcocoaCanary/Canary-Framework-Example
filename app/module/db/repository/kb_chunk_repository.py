import uuid
from datetime import datetime
from typing import Optional, Any, Sequence

from canary_framework import service, after_init
from canary_framework.core.service import ServiceBase
from sqlalchemy import create_engine
from sqlmodel import Session, select

from config import AppConfig
from app.module.db.models import KbChunk


@service()
class KbChunkRepository(ServiceBase):
    config: AppConfig

    @after_init
    async def after_init(self):
        self.engine = create_engine(self.config.database_url, echo=True)

    def get_session(self):
        return Session(self.engine)

    @staticmethod
    def generate_id() -> str:
        return "kc_" + uuid.uuid4().hex

    def create_chunk(self, file_id: str, kb_id: str, content: str, embedding: Optional[list[float]] = None,
                     chunk_index: int = 0) -> KbChunk:
        with self.get_session() as session:
            chunk = KbChunk(
                id=self.generate_id(),
                file_id=file_id,
                kb_id=kb_id,
                content=content,
                embedding=embedding,
                chunk_index=chunk_index,
                created_at=datetime.utcnow(),
            )
            session.add(chunk)
            session.commit()
            session.refresh(chunk)
            return chunk

    def get_chunk(self, chunk_id: str) -> type[KbChunk] | None:
        with self.get_session() as session:
            return session.get(KbChunk, chunk_id)

    def update_chunk(self, chunk_id: str, **kwargs) -> type[KbChunk] | None:
        with self.get_session() as session:
            chunk = session.get(KbChunk, chunk_id)
            if not chunk:
                return None
            for key, value in kwargs.items():
                if hasattr(chunk, key) and key not in ["id", "created_at"]:
                    setattr(chunk, key, value)
            session.add(chunk)
            session.commit()
            session.refresh(chunk)
            return chunk

    def delete_chunk(self, chunk_id: str) -> bool:
        with self.get_session() as session:
            chunk = session.get(KbChunk, chunk_id)
            if not chunk:
                return False
            session.delete(chunk)
            session.commit()
            return True

    def list_chunks_by_file(self, file_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KbChunk).where(KbChunk.file_id == file_id).order_by(KbChunk.chunk_index)
            return session.exec(statement).all()

    def list_chunks_by_kb(self, kb_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KbChunk).where(KbChunk.kb_id == kb_id)
            return session.exec(statement).all()

    def delete_chunks_by_file(self, file_id: str) -> int:
        with self.get_session() as session:
            statement = select(KbChunk).where(KbChunk.file_id == file_id)
            chunks = session.exec(statement).all()
            count = 0
            for chunk in chunks:
                session.delete(chunk)
                count += 1
            session.commit()
            return count

    def delete_chunks_by_kb(self, kb_id: str) -> int:
        with self.get_session() as session:
            statement = select(KbChunk).where(KbChunk.kb_id == kb_id)
            chunks = session.exec(statement).all()
            count = 0
            for chunk in chunks:
                session.delete(chunk)
                count += 1
            session.commit()
            return count
