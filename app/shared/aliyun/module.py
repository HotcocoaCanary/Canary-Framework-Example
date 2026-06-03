from canary_framework import module

from app.shared.aliyun.service.oss_service import OssService
from app.shared.aliyun.service.qwen_service import QwenService


@module(
    services=[
        OssService,
        QwenService,
    ],
)
class AliyunModule:
    pass
