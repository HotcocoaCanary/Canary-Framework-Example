from canary_framework import module

from app.module.chat_module.router.chat_router import ChatRouter
from app.module.chat_module.router.session_router import SessionRouter
from app.module.chat_module.service.rag_service import RAGService
from app.module.chat_module.service.session_service import SessionService


@module(name="ChatModule", services=[SessionService, RAGService, ChatRouter, SessionRouter])
class ChatModule:
    pass
