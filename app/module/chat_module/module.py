from app.module.chat_module.service.rag_service import RAGService
from app.module.chat_module.service.session_service import SessionService
from canary_framework import module


@module(name="ChatModule", services=[SessionService, RAGService])
class ChatModule:
    pass
