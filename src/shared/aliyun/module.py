from canary_framework import module

from app import OSSClient


@module(name="AliyunModule", services=[OSSClient])
class AliyunModule:
    pass
