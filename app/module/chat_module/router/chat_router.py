from canary_framework import Context
from canary_framework.web.fastapi import router, post
from fastapi import Depends

from app.common.depends import get_current_user
from app.module.chat_module.schema import ChatCompletionRequest


@router(prefix="/v1")
class ChatRouter:
    def __init__(self, ctx: Context):
        from app.module.chat_module.service.rag_service import RAGService
        self.svc = ctx.resolve(RAGService)

    @post("/chat/completions", tags=["问答"], summary="RAG 问答 (OpenAI 兼容)",
          description="支持流式 (SSE) 和非流式返回。session_id 为 null 时自动创建新会话。"
                      "knowledge_scope 为空时使用用户所有知识库作为检索范围。")
    async def chat_completions(self, req: ChatCompletionRequest, user=Depends(get_current_user)):
        return await self.svc.chat_completions(user, req)
