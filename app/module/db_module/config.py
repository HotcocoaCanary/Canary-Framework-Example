from canary_framework import config


@config
class DBConfig:
    postgres_user: str
    postgres_password: str
    postgres_base: str
    postgres_db: str

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_base}/{self.postgres_db}"
