from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cf_log_level: str

    host: str
    port: int

    postgres_user: str
    postgres_password: str
    postgres_base: str
    postgres_db: str

    pigx_base: str

    oss_endpoint: str
    oss_region: str
    oss_bucket: str
    oss_access_key: str
    oss_secret_key: str

    litellm_api_base: str
    litellm_port: int
    litellm_api_key: str

    DASHSCOPE_API_KEY: str
    DASHSCOPE_API_BASE: str

    QWEN_OCR_SYSTEM_PROMPT: str

    @computed_field
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_base}/{self.postgres_db}"

    @computed_field
    @property
    def litellm_url(self) -> str:
        return f"{self.litellm_api_base}:{self.litellm_port}"
