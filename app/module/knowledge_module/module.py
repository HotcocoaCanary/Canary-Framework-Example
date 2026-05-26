from app.module.knowledge_module.service.kb_service import KbService
from canary_framework import module


@module(name="KnowledgeModule", services=[KbService])
class KnowledgeModule:
    pass
