from canary_framework import service
from canary_framework.core.service import ServiceBase

from config import AppConfig


@service()
class OssService(ServiceBase):
    config: AppConfig
