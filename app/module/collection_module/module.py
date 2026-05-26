from app.module.collection_module.service.collection_service import CollectionService
from canary_framework import module


@module(name="CollectionModule", services=[CollectionService])
class CollectionModule:
    pass
