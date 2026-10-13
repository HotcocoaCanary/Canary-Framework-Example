"""Retrieval — chunking, indexing and semantic search over the corpus."""

from __future__ import annotations

import asyncio

from canary_framework import scope_of

from app.module.rag.chunker import TextChunker
from app.testing import failure, make_book, payload
from config import AppConfig

POLICY = (
    "普通读者一次最多可借 5 册，借期 30 天，可续借 2 次。"
    "逾期每天每册罚款 0.5 元。VIP 读者借期为 60 天，最多可借 10 册。"
)
OPENING = "本馆开放时间为周一至周日 9:00 至 21:00，法定节假日闭馆。古籍阅览室仅在周三下午开放。"


async def _index(client, title, text, **extra) -> dict:
    return payload(await client.post("/api/rag/documents", json={"title": title, "text": text, **extra}))


def _chunker(**settings) -> TextChunker:
    """A chunker on a graph of its own.

    任何单元都可以当根启动——这里这张图只有两个节点：``TextChunker`` 和它依赖的
    ``AppConfig``，而后者由测试预先登记，于是切分参数完全由测试说了算。
    """
    chunker = TextChunker()
    scope_of(chunker).provide(AppConfig, AppConfig(**settings))
    asyncio.run(chunker.init())
    return chunker


# --- 切分 -------------------------------------------------------------


def test_chunker_splits_on_sentence_boundaries():
    pieces = _chunker().split("第一句。第二句！第三句？")
    assert pieces == ["第一句。第二句！第三句？"]  # 短文本合并为一段


def test_chunker_respects_the_window_and_overlaps():
    chunker = _chunker(chunk_size=40, chunk_overlap=10)

    pieces = chunker.split("。".join(f"这是第 {i} 个句子内容" for i in range(20)))
    assert len(pieces) > 1
    assert all(len(p) <= 40 + 10 for p in pieces)


def test_chunker_hard_cuts_a_sentence_longer_than_the_window():
    pieces = _chunker(chunk_size=20, chunk_overlap=0).split("甲" * 95)
    assert len(pieces) >= 5
    assert max(len(p) for p in pieces) <= 20


# --- 建索引 -----------------------------------------------------------


async def test_indexing_a_document_produces_chunks(client):
    doc = await _index(client, "借阅规则", POLICY, source="policy")
    assert doc["status"] == "indexed"
    assert doc["chunk_count"] >= 1
    assert doc["source"] == "policy"


async def test_indexing_rejects_an_unknown_source(client):
    code, msg = failure(await client.post("/api/rag/documents", json={
        "title": "x", "text": "y", "source": "wherever"}))
    assert code == 422
    assert "来源" in msg


async def test_indexing_rejects_a_missing_book(client):
    code, _ = failure(await client.post("/api/rag/documents", json={
        "title": "x", "text": "y", "book_id": "bk_nope"}))
    assert code == 404


async def test_a_book_card_is_itself_indexable(client):
    book = await make_book(client, summary="讲解进程间通信、一致性与复制、分布式事务与容错。", tags=["分布式"])
    doc = payload(await client.post(f"/api/rag/books/{book['id']}/index"))
    assert doc["source"] == "catalog"
    assert doc["book_id"] == book["id"]
    assert doc["status"] == "indexed"

    hits = payload(await client.get("/api/rag/search", params={"q": "一致性与复制"}))["passages"]
    assert hits
    assert hits[0]["book_id"] == book["id"]
    assert hits[0]["book_title"] == book["title"]


async def test_reindexing_a_book_card_replaces_the_previous_one(client):
    book = await make_book(client, summary="第一版简介。")
    payload(await client.post(f"/api/rag/books/{book['id']}/index"))
    payload(await client.post(f"/api/rag/books/{book['id']}/index"))
    page = payload(await client.get("/api/rag/documents", params={"book_id": book["id"]}))
    assert page["total"] == 1


async def test_reindex_rebuilds_the_chunks(client):
    doc = await _index(client, "借阅规则", POLICY, source="policy")
    again = payload(await client.post(f"/api/rag/documents/{doc['id']}/reindex"))
    assert again["status"] == "indexed"
    assert again["chunk_count"] == doc["chunk_count"]

    hits = payload(await client.get("/api/rag/search", params={"q": "续借几次"}))["passages"]
    assert len({p["chunk_id"] for p in hits}) == len(hits)  # 没有留下重复片段


async def test_empty_text_is_rejected_by_the_request_model(client):
    response = await client.post("/api/rag/documents", json={"title": "x", "text": ""})
    assert response.status_code == 422


async def test_deleting_a_document_removes_it_from_search(client):
    doc = await _index(client, "开放时间", OPENING, source="policy")
    assert payload(await client.get("/api/rag/search", params={"q": "开放时间"}))["passages"]

    payload(await client.delete(f"/api/rag/documents/{doc['id']}"))
    assert payload(await client.get("/api/rag/search", params={"q": "开放时间"}))["passages"] == []


# --- 检索 -------------------------------------------------------------


async def test_search_ranks_the_relevant_document_first(client):
    await _index(client, "借阅规则", POLICY, source="policy")
    await _index(client, "开放时间", OPENING, source="policy")

    hits = payload(await client.get("/api/rag/search", params={"q": "古籍阅览室什么时候开放"}))["passages"]
    assert hits
    assert hits[0]["doc_title"] == "开放时间"
    assert hits[0]["score"] > 0


async def test_search_can_be_scoped_to_one_book(client):
    first = await make_book(client, title="分布式系统", summary="讲解一致性与复制。", isbn=None)
    second = await make_book(client, title="操作系统导论", summary="讲解进程调度与虚拟内存。", isbn=None)
    payload(await client.post(f"/api/rag/books/{first['id']}/index"))
    payload(await client.post(f"/api/rag/books/{second['id']}/index"))

    scoped = payload(await client.get(
        "/api/rag/search", params={"q": "讲解什么", "book_id": second["id"]}))["passages"]
    assert scoped
    assert {p["book_id"] for p in scoped} == {second["id"]}


async def test_search_honours_top_k(client):
    for index in range(5):
        await _index(client, f"资料 {index}", f"图书馆资料第 {index} 份，内容涉及借阅与阅览。")
    hits = payload(await client.get("/api/rag/search", params={"q": "借阅与阅览", "top_k": 2}))["passages"]
    assert len(hits) == 2


async def test_search_returns_nothing_when_the_corpus_is_empty(client):
    assert payload(await client.get("/api/rag/search", params={"q": "任何问题"}))["passages"] == []


async def test_blank_query_is_rejected(client):
    code, msg = failure(await client.get("/api/rag/search", params={"q": "   "}))
    assert code == 422
    assert "不能为空" in msg


async def test_document_listing_filters_by_status_and_book(client):
    book = await make_book(client, summary="简介。")
    payload(await client.post(f"/api/rag/books/{book['id']}/index"))
    await _index(client, "借阅规则", POLICY, source="policy")

    assert payload(await client.get("/api/rag/documents"))["total"] == 2
    assert payload(await client.get("/api/rag/documents", params={"book_id": book["id"]}))["total"] == 1
    assert payload(await client.get("/api/rag/documents", params={"status": "indexed"}))["total"] == 2


async def test_getting_a_missing_document(client):
    code, _ = failure(await client.get("/api/rag/documents/doc_nope"))
    assert code == 404
