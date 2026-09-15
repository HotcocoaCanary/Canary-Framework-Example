"""Application settings — a plain ``@cocoa`` unit again.

配置在框架里没有特殊地位。0.9.3 曾把它做成"类级注解即声明"的注入源
（``app_config: AppConfig`` 自动填），HEAD 把那条路整个删了，连
``canary_framework.Config`` 基类也一并删了——理由是配置就是一个普通节点，
不该由框架多认识一种声明方式。

于是它回到最朴素的写法：一个 ``pydantic-settings`` 的类，加上 ``@cocoa``，
谁要用谁就写进 ``deps=[AppConfig]``，注入名 ``self.app_config`` 由类名推出。
好处是它现在是图上的一个真节点——``canary[AppConfig]`` 直接取得到，
测试要改几个字段，改 ``init()`` 之后那一份共享实例就够了（整张图拿的是同一个对象）。

可插拔的模型实现则由 ``embedding_provider`` / ``chat_provider`` 决定：最终版删掉了
``provide=``，"用哪个实现"因此回到单元内部（见 ``app/infra/ai.py``）。
"""

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from canary_framework import cocoa


@cocoa
class AppConfig(BaseSettings):
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
