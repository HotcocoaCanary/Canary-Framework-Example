from canary_framework import module
from canary_framework.core.module import ModuleBase

from app.shared.aliyun.service.oss_service import OssService
from app.shared.aliyun.service.qwen_service import QwenService


@module(
    services=[
        OssService,
        QwenService,
    ],
)
class AliyunModule(ModuleBase):
    pass
