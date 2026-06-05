from canary_framework import module
from canary_framework.core.module import ModuleBase

from app.module.file.service import FileService
from app.module.file.router import FileRouter


@module(
    services=[
        FileService,
        FileRouter,
    ],
)
class FileModule(ModuleBase):
    pass
