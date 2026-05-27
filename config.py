from pydantic_settings import BaseSettings, SettingsConfigDict

from app.module.db_module.config import DBConfig
from app.shared.aliyun.config import AliyunConfig
from app.shared.embedding.config import EmbeddingConfig
from app.shared.llm.config import LLMConfig
from app.shared.pigx.config import PigXConfig


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8000
    fastapi_title: str = "Canary-Agent"
    fastapi_version: str = "0.1.0"
    fastapi_description: str = "基于 Canary Framework + LangGraph 的 AI 平台"

    DBService: DBConfig = DBConfig()
    AuthService: PigXConfig = PigXConfig()
    OSSClient: AliyunConfig = AliyunConfig()
    LLMClient: LLMConfig = LLMConfig()
    EmbeddingService: EmbeddingConfig = EmbeddingConfig()
