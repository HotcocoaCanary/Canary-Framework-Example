from canary_framework import module

from app.shared.aliyun.config import AliyunConfig
from app.shared.aliyun.service.oss_service import OSSClient


@module(name="AliyunModule", services=[OSSClient], config=AliyunConfig)
class AliyunModule:
    pass
