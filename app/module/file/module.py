from canary_framework import cocoa

from app.module.file.router import FileRouter
from app.module.file.service import FileService


@cocoa(deps=[FileService])
class FileModule:
    pass
