from app.module.knowledge_module.service.file_service import FileService
from app.module.knowledge_module.service.kb_service import KbService
from app.module.knowledge_module.service.parse_service import ParseService
from canary_framework import module


@module(name="KnowledgeModule", services=[KbService, FileService, ParseService])
class KnowledgeModule:
    pass
