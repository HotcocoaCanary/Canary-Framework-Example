from app.module.file_module.service.file_service import FileService
from canary_framework import module


@module(name="FileModule", services=[FileService])
class FileModule:
    pass
