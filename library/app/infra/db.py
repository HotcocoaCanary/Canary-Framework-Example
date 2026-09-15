"""Database — the one unit that owns the engine, the schema and the unit of work.

引擎只有一份：这一个单元持有它，仓储是无状态的查询对象，会话由调用方传进去，
而**服务**负责开会话——于是服务的方法边界就是事务边界。若让每个仓储各自建引擎，
就会变成一个仓储一个连接池，两个仓储也无法共享同一个事务。

框架的作用域是"一次运行"而不是"一次请求"：一个作用域内每个类型只有一个实例，这正是
连接池该有的粒度，但也意味着没有请求级的工作单元。所以事务边界由应用显式划出来——
``async with self.database.begin()``。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from canary_framework import Canary, dep, start, stop
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from config import AppConfig


class Database(Canary):
    """Owns the async engine and hands out sessions.

    依赖从 ``@init`` 起就可用，而 ``@start`` 又在依赖的 ``@start`` 之后运行，
    所以这里读得到最终的配置。
    """

    config = dep(AppConfig)

    engine: AsyncEngine
    _sessionmaker: async_sessionmaker[AsyncSession]

    @start
    async def connect(self) -> None:
        self.engine = create_async_engine(
            self.config.database_url,
            echo=self.config.sql_echo,
            # 内存库必须共用一条连接，否则每个连接看到的是各自的空库。
            **({"poolclass": _static_pool()} if self._is_memory else {}),
        )
        self._sessionmaker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        if self.config.storage != "postgres":
            # PostgreSQL 的表结构由 alembic 迁移管理；SQLite 开发/测试库直接建表。
            await self.create_all()

    @stop
    async def disconnect(self) -> None:
        await self.engine.dispose()

    @property
    def dialect(self) -> str:
        return "postgres" if self.config.storage == "postgres" else "sqlite"

    @property
    def _is_memory(self) -> bool:
        return self.config.storage != "postgres" and self.config.sqlite_path == ":memory:"

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
