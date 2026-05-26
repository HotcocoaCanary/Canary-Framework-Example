from app.agent.state.rag_state import RAGState


async def retrieve_node(state: RAGState, config: dict = None) -> RAGState:
    if config is None:
        config = {}
    configurable = config.get("configurable", {})
    chunk_repo = configurable.get("chunk_repo")
    llm_client = configurable.get("llm_client")
    file_repo = configurable.get("file_repo")

    embedding_list = await llm_client.embed([state["query"]])
    query_embedding = embedding_list[0]
    chunks = await chunk_repo.search(
        embedding=query_embedding,
        kb_ids=state["kb_ids"],
        file_ids=state["file_ids"],
        top_k=state["top_k"],
    )
    retrieved = []
    sources = []
    for chunk in chunks:
        f = await file_repo.get_by_id(chunk.file_id)
        retrieved.append({"content": chunk.content, "file_id": chunk.file_id, "chunk_index": chunk.chunk_index})
        sources.append({
            "file_name": f.name if f else "",
            "file_type": f.file_type if f else "",
            "oss_url": f.oss_url if f else "",
            "chunk_index": chunk.chunk_index,
            "content": chunk.content[:500],
        })
    state["retrieved_chunks"] = retrieved
    state["sources"] = sources
    return state


def build_prompt_node(state: RAGState, config: dict = None) -> RAGState:
    history_text = ""
    for msg in state.get("history", []):
        role = "用户" if msg["role"] == "user" else "助手"
        history_text += f"{role}: {msg['content']}\n"

    context = "\n\n".join([c["content"] for c in state["retrieved_chunks"]])

    prompt = f"""你是一个知识库问答助手。请根据以下参考资料回答用户问题。

## 历史对话
{history_text}

## 参考资料
{context}

## 用户问题
{state["query"]}

## 回答要求
- 如果参考资料不足,请诚实告知
- 回答要准确、简洁、有依据
- 使用 Markdown 格式"""
    state["prompt"] = prompt
    return state
