"""Application settings — a unit that is also a pydantic model.

0.10.0 的单元就是普通 Python 类，所以配置不必在"pydantic 模型"和"图上的节点"之间
二选一，两个基类一起继承即可::

    class AppConfig(BaseSettings, Canary): ...

``BaseSettings`` 读 ``.env`` 与环境变量，``Canary`` 让它成为图上的一个节点：谁要用谁写
``config = dep(AppConfig)``，整张图共享同一个实例。

配置在框架里没有任何特殊地位——0.9.x 一度把它做成"类级注解即声明"的注入源，还配了一个
``canary_framework.Config`` 基类，那条路连同整个装饰器体系一起删掉了。

可插拔的模型实现由 ``embedding_provider`` / ``chat_provider`` 决定，由单元自己读
（见 ``app/infra/ai.py``）：框架没有装配期的替换入口，图上的实例一律由框架无参构造。
"""

from canary_framework import Canary
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings, Canary):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    log_level: str = "DEBUG"

    # -- storage ------------------------------------------------------
    # ``sqlite`` runs the whole system with no external service (dev + tests);
    # ``postgres`` uses PostgreSQL + pgvector.
    storage: str = "sqlite"
    sqlite_path: str = ":memory:"
    sql_echo: bool = False

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_base: str = "localhost:5432"
    postgres_db: str = "ly_library"

    # -- AI -----------------------------------------------------------
    # ``local`` = deterministic offline implementations (no network, used by the
    # test-suite and by ``storage=sqlite`` dev runs).
    # ``openai`` = any OpenAI-compatible endpoint (litellm, DashScope, vLLM …).
    embedding_provider: str = "local"
    chat_provider: str = "local"
    embedding_dim: int = 1024

    llm_api_base: str = "http://localhost:4100"
    llm_api_key: str = "sk-litellm"
    embedding_model_name: str = "text-embedding-v3"
    chat_model_name: str = "qwen-plus"
    llm_timeout_seconds: float = 30.0

    # -- RAG ----------------------------------------------------------
    chunk_size: int = 400
    chunk_overlap: int = 80
    retrieve_top_k: int = 5
    min_similarity: float = 0.05

    # -- 图书馆业务规则 -------------------------------------------------
    loan_days_default: int = 30
    loan_days_by_level: dict[str, int] = {
        "student": 30,
        "normal": 30,
        "vip": 60,
        "staff": 90,
    }
    max_loans_by_level: dict[str, int] = {
        "student": 5,
        "normal": 5,
        "vip": 10,
        "staff": 20,
    }
    max_renews: int = 2
    fine_cents_per_overdue_day: int = 50
    max_fine_cents_before_block: int = 2000
    reservation_hold_hours: int = 48

    @computed_field
    @property
    def database_url(self) -> str:
        if self.storage == "postgres":
            return (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_base}/{self.postgres_db}"
            )
        return f"sqlite+aiosqlite:///{self.sqlite_path}"

    def loan_days(self, level: str) -> int:
        return self.loan_days_by_level.get(level, self.loan_days_default)

    def max_loans(self, level: str) -> int:
        return self.max_loans_by_level.get(level, 5)
