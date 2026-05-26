from canary_framework import module

from app.module.chat_module.service.rag_service import RAGService
from app.module.chat_module.service.session_service import SessionService


@module(name="ChatModule", services=[SessionService, RAGService])
class ChatModule:
    pass
