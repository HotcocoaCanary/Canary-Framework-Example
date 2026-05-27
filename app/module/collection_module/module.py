from canary_framework import module

from app.module.collection_module.router.collection_router import CollectionRouter
from app.module.collection_module.service.collection_service import CollectionService


@module(name="CollectionModule", services=[CollectionService, CollectionRouter])
class CollectionModule:
    pass
