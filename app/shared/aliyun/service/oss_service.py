from canary_framework import service

from app.config import AppConfig


@service()
class OssService:
    config: AppConfig
