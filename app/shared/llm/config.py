from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    litellm_api_base: str = ""
    litellm_port: int = 0
    litellm_api_key: str = ""
    embedding_model: str = "qwen-embedding"

    @property
    def litellm_url(self) -> str:
        return f"{self.litellm_api_base}:{self.litellm_port}"
