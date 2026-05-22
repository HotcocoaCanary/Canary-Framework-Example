from cf import config


@config
class DBConfig:
    postgres_username: str = "postgres"
    postgres_password: str = "postgres"
    postgres_base: str = "localhost:5432"
    postgres_database: str = "ly_ai_agent"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_username}:{self.postgres_password}@{self.postgres_base}/{self.postgres_database}"
