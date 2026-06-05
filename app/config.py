import os
from pathlib import Path
from pydantic import Field, computed_field
from canary_framework import config as cf_config
from canary_framework.common.config import CanaryConfig
from canary_framework.core.service import ServiceBase


def load_env(env_path: str = ".env") -> None:
    """Load .env file into os.environ so AppConfig defaults pick up values."""
    env_file = Path(env_path)
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key not in os.environ:
            os.environ[key] = value


@cf_config()
class AppConfig(CanaryConfig, ServiceBase):
    _cf_hooks = None
    _cf_parent_registry = None

    host: str = Field(default_factory=lambda: os.environ.get("HOST", "localhost"))
    port: int = Field(default_factory=lambda: int(os.environ.get("PORT", "8010")))
    log_level: str = Field(default_factory=lambda: os.environ.get("CF_LOG_LEVEL", "DEBUG"))

    postgres_user: str = Field(default_factory=lambda: os.environ.get("POSTGRES_USER", "postgres"))
    postgres_password: str = Field(default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", "postgres"))
    postgres_base: str = Field(default_factory=lambda: os.environ.get("POSTGRES_BASE", "localhost:5432"))
    postgres_db: str = Field(default_factory=lambda: os.environ.get("POSTGRES_DB", "ly_ai_agent"))

    pigx_base: str = Field(default_factory=lambda: os.environ.get("PIGX_BASE", "http://127.0.0.1:9100"))

    oss_endpoint: str = Field(default_factory=lambda: os.environ.get("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com"))
    oss_region: str = Field(default_factory=lambda: os.environ.get("OSS_REGION", "cn-hangzhou"))
    oss_bucket: str = Field(default_factory=lambda: os.environ.get("OSS_BUCKET", "ly-teach-video"))
    oss_access_key: str = Field(default_factory=lambda: os.environ.get("OSS_ACCESS_KEY", ""))
    oss_secret_key: str = Field(default_factory=lambda: os.environ.get("OSS_SECRET_KEY", ""))

    litellm_api_base: str = Field(default_factory=lambda: os.environ.get("LITELLM_API_BASE", "http://localhost"))
    litellm_port: int = Field(default_factory=lambda: int(os.environ.get("LITELLM_PORT", "4100")))
    litellm_api_key: str = Field(default_factory=lambda: os.environ.get("LITELLM_API_KEY", "sk-litellm"))

    DASHSCOPE_API_KEY: str = Field(default_factory=lambda: os.environ.get("DASHSCOPE_API_KEY", ""))
    DASHSCOPE_API_BASE: str = Field(default_factory=lambda: os.environ.get("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"))

    QWEN_OCR_SYSTEM_PROMPT: str = Field(default_factory=lambda: os.environ.get("QWEN_OCR_SYSTEM_PROMPT", "Please output only the text content from the image without any additional descriptions or formatting."))

    @computed_field
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_base}/{self.postgres_db}"

    @computed_field
    @property
    def litellm_url(self) -> str:
        return f"{self.litellm_api_base}:{self.litellm_port}"
