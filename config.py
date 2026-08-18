from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from canary_framework import cocoa


@cocoa
class AppConfig(BaseSettings):
    """Application settings exposed as a Canary 0.9 cocoa dependency.

    Canary Framework 0.9 intentionally keeps configuration out of the core;
    settings are ordinary Python objects and are injected through ``deps``.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    log_level: str = "DEBUG"

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_base: str = "localhost:5432"
    postgres_db: str = "ly_ai_agent"

    pigx_base: str = "http://127.0.0.1:9100"

    oss_endpoint: str = "oss-cn-hangzhou.aliyuncs.com"
    oss_region: str = "cn-hangzhou"
    oss_bucket: str = "ly-teach-video"
    oss_access_key: str = ""
    oss_secret_key: str = ""

    litellm_api_base: str = "http://localhost"
    litellm_port: int = 4100
    litellm_api_key: str = "sk-litellm"

    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    QWEN_OCR_SYSTEM_PROMPT: str = "Please output only the text content from the image without any additional descriptions or formatting."

    @computed_field
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_base}/{self.postgres_db}"

    @computed_field
    @property
    def litellm_url(self) -> str:
        return f"{self.litellm_api_base}:{self.litellm_port}"
