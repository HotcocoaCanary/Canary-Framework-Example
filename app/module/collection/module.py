from canary_framework import module
from canary_framework.core.module import ModuleBase

from app.module.collection.service import CollService
from app.module.collection.router import CollRouter


@module(
    services=[
        CollService,
        CollRouter,
    ],
)
class CollModule(ModuleBase):
    pass
