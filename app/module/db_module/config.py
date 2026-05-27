from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_base: str = "localhost:5432"
    postgres_db: str = "ly_ai_agent"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_base}/{self.postgres_db}"
