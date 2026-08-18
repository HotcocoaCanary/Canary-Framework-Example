from canary_framework import cocoa

from app.module.kb.router import KBRouter
from app.module.kb.service import KbService


@cocoa(deps=[KbService])
class KBModule:
    pass
