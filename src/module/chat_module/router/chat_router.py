from canary_framework import router, post

from app import get_current_user
from src.module.chat_module.schema import ChatCompletionRequest
from src.module.chat_module.service.rag_service import RAGService
from app import AuthService


@router(name="chat_api", prefix="/v1", deps=[RAGService, AuthService])
class ChatRouter:
    rag_service: RAGService
    auth_service: AuthService

    @post("/chat/completions", request_model=ChatCompletionRequest, tags=["问答"], summary="RAG 问答 (OpenAI 兼容)",
          description="支持流式 (SSE) 和非流式返回。session_id 为 null 时自动创建新会话。"
                      "knowledge_scope 为空时使用用户所有知识库作为检索范围。")
    async def chat_completions(self, request, req: ChatCompletionRequest):
        user = await get_current_user(request, self.auth_service)
        return await self.rag_service.chat_completions(user, req)
