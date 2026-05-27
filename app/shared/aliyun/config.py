from pydantic_settings import BaseSettings, SettingsConfigDict


class AliyunConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    oss_endpoint: str = ""
    oss_region: str = ""
    oss_bucket: str = ""
    oss_access_key: str = ""
    oss_secret_key: str = ""
