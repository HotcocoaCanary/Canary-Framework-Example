from typing import TypedDict, Optional


class RAGState(TypedDict):
    query: str
    history: list[dict]
    kb_ids: list[str]
    file_ids: Optional[list[str]]
    top_k: int
    retrieved_chunks: list[dict]
    prompt: str
    answer: str
    sources: list[dict]