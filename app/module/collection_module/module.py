from canary_framework import module

from app.module.collection_module.service.collection_service import CollectionService


@module(name="CollectionModule", services=[CollectionService])
class CollectionModule:
    pass
