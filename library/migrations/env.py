import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app.module.db.models import *  # noqa: F401, F403
from config import AppConfig

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

def build_database_url() -> str:
    """Migrations always target PostgreSQL, whatever ``storage`` says.

    ``AppConfig`` is an ordinary ``BaseSettings`` object — usable outside the
    Canary graph — so alembic reads exactly the same ``.env`` the application does.
    """
    settings = AppConfig(storage="postgres")
    return settings.database_url


def run_migrations_offline() -> None:
    url = build_database_url()
    sync_url = url.replace("+asyncpg", "")
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        build_database_url(),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
