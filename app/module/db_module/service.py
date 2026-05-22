import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.module.db_module.repository.chunk_repo import ChunkRepo
from app.module.db_module.repository.file_record_repo import FileRecordRepo
from app.module.db_module.repository.kb_repo import KbRepo
from app.module.db_module.repository.member_repo import MemberRepo
from app.module.db_module.repository.message_repo import MessageRepo
from app.module.db_module.repository.node_repo import NodeRepo
from app.module.db_module.repository.parse_repo import ParseRepo
from app.module.db_module.repository.session_repo import SessionRepo
from cf import service, on_init, on_start, on_end, ServiceContext

logger = logging.getLogger(__name__)


@service(name="DBService")
class DBService:
    @on_init
    async def init(self, ctx: ServiceContext):
        self._engine = create_async_engine(
            ctx.config.database_url,
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

    def node_repo(self, session: AsyncSession) -> NodeRepo:
        return NodeRepo(session)

    def file_record_repo(self, session: AsyncSession) -> FileRecordRepo:
        return FileRecordRepo(session)

    def parse_repo(self, session: AsyncSession) -> ParseRepo:
        return ParseRepo(session)

    def chunk_repo(self, session: AsyncSession) -> ChunkRepo:
        return ChunkRepo(session)

    def session_repo(self, session: AsyncSession) -> SessionRepo:
        return SessionRepo(session)

    def message_repo(self, session: AsyncSession) -> MessageRepo:
        return MessageRepo(session)
