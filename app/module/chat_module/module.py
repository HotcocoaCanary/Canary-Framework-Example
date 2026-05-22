from app.module.chat_module.service.rag_service import RAGService
from app.module.chat_module.service.session_service import SessionService
from cf import module


@module(name="ChatModule", services=[SessionService, RAGService])
class ChatModule:
    pass
