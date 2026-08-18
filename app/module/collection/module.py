from canary_framework import cocoa

from app.module.collection.service import CollService


@cocoa(deps=[CollService])
class CollModule:
    pass
