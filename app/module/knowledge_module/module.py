from canary_framework import module

from app.module.knowledge_module.router.kb_router import KbRouter
from app.module.knowledge_module.service.kb_service import KbService


@module(name="KnowledgeModule", services=[KbService, KbRouter])
class KnowledgeModule:
    pass
