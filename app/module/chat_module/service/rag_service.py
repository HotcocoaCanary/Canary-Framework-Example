import json
import logging
import uuid

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.agent import RAGState, build_rag_graph
from app.module.chat_module.router.chat_router import ChatRouter
from app.module.chat_module.schema import ChatCompletionRequest
from app.module.db_module.models import Session, Message
from app.module.db_module.service import DBService
from app.shared.llm.client import LLMClient
from app.common.types import UserContext
from canary_framework import service, on_init, Context
from canary_framework.web.fastapi import web

logger = logging.getLogger(__name__)


@web(routers=[ChatRouter])
@service(name="RAGService", deps=[DBService, LLMClient])
class RAGService:
    @on_init
    def init(self, ctx: Context):
        pass

    async def chat_completions(self, user: UserContext, req: ChatCompletionRequest):
        session_id = req.session_id
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:20]}"
            sess = Session(
                id=session_id,
                user_id=user.user_id,
                name=req.content[:50],
            )
            async with self.db_service.transaction() as s:
                session_repo = self.db_service.session_repo(s)
                await session_repo.create(sess)

        async with self.db_service.transaction() as s:
            session_repo = self.db_service.session_repo(s)
            message_repo = self.db_service.message_repo(s)

            sess_check = await session_repo.get_by_id(session_id)
            if not sess_check:
                raise HTTPException(status_code=404, detail="会话不存在")
            if sess_check.user_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限")

            if not sess_check.name or sess_check.name == "":
                sess_check.name = req.content[:50]
                await session_repo.update(sess_check)

        if req.stream:
            return StreamingResponse(
                self._chat_stream(session_id, user, req),
                media_type="text/event-stream",
            )
        else:
            result = await self._chat(session_id, user, req)
            return result

    async def _chat_stream(self, session_id: str, user: UserContext, req: ChatCompletionRequest):
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

        async with self.db_service.transaction() as s:
            kb_repo = self.db_service.kb_repo(s)
            member_repo = self.db_service.member_repo(s)
            node_repo = self.db_service.node_repo(s)
            chunk_repo = self.db_service.chunk_repo(s)
            message_repo = self.db_service.message_repo(s)

            history_messages = await message_repo.get_history_content(session_id)
            history = [{"role": m.role, "content": m.content} for m in history_messages]

            kb_ids = []
            file_ids = []
            if req.knowledge_scope:
                for scope in req.knowledge_scope:
                    kb_ids.append(scope.knowledge_id)
                    file_ids.extend(scope.file_ids)
            else:
                member_kb_ids = await member_repo.list_by_user(user.user_id)
                kb_ids = member_kb_ids

            graph = build_rag_graph()
            initial_state: RAGState = {
                "query": req.content,
                "history": history,
                "kb_ids": kb_ids,
                "file_ids": file_ids if file_ids else None,
                "top_k": 5,
                "retrieved_chunks": [],
                "prompt": "",
                "answer": "",
                "sources": [],
            }

            final_state = await graph.ainvoke(initial_state, config={
                "callbacks": None,
                "configurable": {
                    "chunk_repo": chunk_repo,
                    "llm_client": self.llm_client,
                    "node_repo": node_repo,
                }
            })

            messages = [
                {"role": "system", "content": "你是一个知识库问答助手,请使用 Markdown 格式回答。"},
                *history,
                {"role": "user", "content": final_state["prompt"]},
            ]

            full_answer = ""
            response = await self.llm_client.chat_stream(messages=messages)

            async for chunk in response:
                if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        content = delta.content
                        full_answer += content
                        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
                        data = json.dumps({
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "choices": [{"delta": {"content": content}, "index": 0}],
                        }, ensure_ascii=False)
                        yield f"event: message\ndata: {data}\n\n"

            final_chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            final_data = json.dumps({
                "id": final_chunk_id,
                "object": "chat.completion.chunk",
                "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
                "sources": final_state["sources"],
            }, ensure_ascii=False)
            yield f"event: message\ndata: {final_data}\n\n"
            yield "data: [DONE]\n\n"

        async with self.db_service.transaction() as s:
            message_repo = self.db_service.message_repo(s)
            user_msg = Message(
                id=f"msg_{uuid.uuid4().hex[:20]}",
                session_id=session_id,
                role="user",
                content=req.content,
            )
            await message_repo.create(user_msg)

            assistant_msg = Message(
                id=f"msg_{uuid.uuid4().hex[:20]}",
                session_id=session_id,
                role="assistant",
                content=full_answer,
                sources=final_state["sources"],
            )
            await message_repo.create(assistant_msg)

    async def _chat(self, session_id: str, user: UserContext, req: ChatCompletionRequest):
        async with self.db_service.transaction() as s:
            kb_repo = self.db_service.kb_repo(s)
            member_repo = self.db_service.member_repo(s)
            node_repo = self.db_service.node_repo(s)
            chunk_repo = self.db_service.chunk_repo(s)
            message_repo = self.db_service.message_repo(s)

            history_messages = await message_repo.get_history_content(session_id)
            history = [{"role": m.role, "content": m.content} for m in history_messages]

            kb_ids = []
            file_ids = []
            if req.knowledge_scope:
                for scope in req.knowledge_scope:
                    kb_ids.append(scope.knowledge_id)
                    file_ids.extend(scope.file_ids)
            else:
                member_kb_ids = await member_repo.list_by_user(user.user_id)
                kb_ids = member_kb_ids

            graph = build_rag_graph()
            initial_state: RAGState = {
                "query": req.content,
                "history": history,
                "kb_ids": kb_ids,
                "file_ids": file_ids if file_ids else None,
                "top_k": 5,
                "retrieved_chunks": [],
                "prompt": "",
                "answer": "",
                "sources": [],
            }

            final_state = await graph.ainvoke(initial_state, config={
                "configurable": {
                    "chunk_repo": chunk_repo,
                    "llm_client": self.llm_client,
                    "node_repo": node_repo,
                }
            })

            messages = [
                {"role": "system", "content": "你是一个知识库问答助手,请使用 Markdown 格式回答。"},
                *history,
                {"role": "user", "content": final_state["prompt"]},
            ]

            response = await self.llm_client.chat(messages=messages, stream=False)
            answer = response.choices[0].message.content

        async with self.db_service.transaction() as s:
            message_repo = self.db_service.message_repo(s)

            user_msg = Message(
                id=f"msg_{uuid.uuid4().hex[:20]}",
                session_id=session_id,
                role="user",
                content=req.content,
            )
            await message_repo.create(user_msg)

            assistant_msg = Message(
                id=f"msg_{uuid.uuid4().hex[:20]}",
                session_id=session_id,
                role="assistant",
                content=answer,
                sources=final_state["sources"],
            )
            await message_repo.create(assistant_msg)

        return {
            "code": 0,
            "data": {
                "session_id": session_id,
                "answer": answer,
                "sources": final_state["sources"],
            },
            "msg": "ok",
        }
