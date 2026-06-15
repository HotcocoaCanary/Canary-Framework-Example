from canary_framework import module
from canary_framework.core.module import ModuleBase

from app.module.kb.router import KBRouter
from app.module.kb.service import KbService


@module(
    services=[
        KbService,
        KBRouter,
    ],
)
class KBModule(ModuleBase):
    pass
