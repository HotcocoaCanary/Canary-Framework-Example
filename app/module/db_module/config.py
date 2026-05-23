from cf import config


@config
class DBConfig:
    postgres_username: str
    postgres_password: str
    postgres_base: str
    postgres_database: str

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_username}:{self.postgres_password}@{self.postgres_base}/{self.postgres_database}"
