from canary_framework import module

from app.module.knowledge_module.service.kb_service import KbService


@module(name="KnowledgeModule", services=[KbService])
class KnowledgeModule:
    pass
