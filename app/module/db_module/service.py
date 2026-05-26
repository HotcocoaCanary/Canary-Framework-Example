import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.module.db_module.config import DBConfig
from app.module.db_module.repository.chunk_repo import ChunkRepo
from app.module.db_module.repository.collection_repo import CollectionRepo
from app.module.db_module.repository.file_repo import FileRepo
from app.module.db_module.repository.kb_repo import KbRepo
from app.module.db_module.repository.member_repo import MemberRepo
from app.module.db_module.repository.message_repo import MessageRepo
from app.module.db_module.repository.session_repo import SessionRepo
from canary_framework import service, on_init, on_start, on_end, Context

logger = logging.getLogger(__name__)


@service(name="DBService")
class DBService:
    @on_init
    async def init(self, ctx: Context):
        self._cfg = ctx.get_config(DBConfig)
        self._engine = create_async_engine(
            self._cfg.database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    @on_start
    async def start(self):
        logger.info("DBService started")

    @on_end
    async def end(self):
        await self._engine.dispose()
        logger.info("DBService shutdown")

    @asynccontextmanager
    async def transaction(self) -> AsyncSession:
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def kb_repo(self, session: AsyncSession) -> KbRepo:
        return KbRepo(session)

    def member_repo(self, session: AsyncSession) -> MemberRepo:
        return MemberRepo(session)

    def file_repo(self, session: AsyncSession) -> FileRepo:
        return FileRepo(session)

    def chunk_repo(self, session: AsyncSession) -> ChunkRepo:
        return ChunkRepo(session)

    def collection_repo(self, session: AsyncSession) -> CollectionRepo:
        return CollectionRepo(session)

    def session_repo(self, session: AsyncSession) -> SessionRepo:
        return SessionRepo(session)

    def message_repo(self, session: AsyncSession) -> MessageRepo:
        return MessageRepo(session)
