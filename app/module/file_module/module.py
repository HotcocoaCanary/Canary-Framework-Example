from canary_framework import module

from app.module.file_module.router.file_router import FileRouter
from app.module.file_module.service.file_service import FileService


@module(name="FileModule", services=[FileService, FileRouter])
class FileModule:
    pass
