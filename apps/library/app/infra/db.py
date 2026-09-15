"""Database — the one unit that owns the engine, the schema and the unit of work.

Every repository used to build its own ``create_engine`` in an ``@on_start``
hook, which meant one connection pool per repository and no way to make two
repositories share a transaction.  Here a single ``@cocoa`` owns the async
engine; repositories are stateless query objects that take the session they must
run in, and a *service* opens the session, making the service boundary the
transaction boundary.

Canary has no request-scoped dependencies (see
``doc/bug/009-no-request-scope-or-unit-of-work.md``), so the unit of work is an
explicit ``async with self.database.begin()`` rather than something the
framework injects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from canary_framework import cocoa, on_start, on_stop
from config import AppConfig


@cocoa(deps=[AppConfig])
class Database:
    """Owns the async engine and hands out sessions.

    ``@on_start`` runs after ``AppConfig`` has been injected (the runtime walks
    the graph in topological order), so the engine can be built from settings.
    """

    app_config: AppConfig

    engine: AsyncEngine
    _sessionmaker: async_sessionmaker[AsyncSession]

    @on_start
    async def connect(self) -> None:
        self.engine = create_async_engine(
            self.app_config.database_url,
            echo=self.app_config.sql_echo,
            # 内存库必须共用一条连接，否则每个连接看到的是各自的空库。
            **({"poolclass": _static_pool()} if self._is_memory else {}),
        )
        self._sessionmaker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        if self.app_config.storage != "postgres":
            # PostgreSQL 的表结构由 alembic 迁移管理；SQLite 开发/测试库直接建表。
            await self.create_all()

    @on_stop
    async def disconnect(self) -> None:
        await self.engine.dispose()

    @property
    def dialect(self) -> str:
        return "postgres" if self.app_config.storage == "postgres" else "sqlite"

    @property
    def _is_memory(self) -> bool:
        return self.app_config.storage != "postgres" and self.app_config.sqlite_path == ":memory:"

    async def create_all(self) -> None:
        """Create every table declared on ``SQLModel.metadata``."""
        from app.module.db import models  # noqa: F401  —— 让所有表完成注册

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncSession]:
        """A unit of work: commits on success, rolls back on any exception."""
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        """A read-only session — no commit, no rollback bookkeeping."""
        async with self._sessionmaker() as session:
            yield session


def _static_pool() -> type:
    from sqlalchemy.pool import StaticPool

    return StaticPool
