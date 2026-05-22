from app.shared.aliyun.config import AliyunConfig
from app.shared.aliyun.service.oss_service import OSSClient
from cf import module


@module(name="AliyunModule", services=[OSSClient], config=AliyunConfig)
class AliyunModule:
    pass
