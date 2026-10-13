"""The librarian assistant — grounded answers, citations and conversation state."""

from __future__ import annotations

from app.infra.ai import NO_ANSWER
from app.testing import failure, make_book, payload

POLICY = (
    "普通读者一次最多可借 5 册，借期 30 天，可续借 2 次。"
    "逾期每天每册罚款 0.5 元。VIP 读者借期为 60 天，最多可借 10 册。"
)


async def _seed_policy(client) -> dict:
    return payload(await client.post("/api/rag/documents", json={
        "title": "借阅规则", "text": POLICY, "source": "policy"}))


async def test_an_answer_cites_the_passages_it_used(client):
    await _seed_policy(client)
    answer = payload(await client.post("/api/assistant/ask", json={"question": "普通读者可以借几册"}))

    assert answer["grounded"] is True
    assert answer["sources"]
    assert answer["sources"][0]["doc_title"] == "借阅规则"
    assert "5 册" in answer["answer"]


async def test_the_assistant_refuses_when_nothing_is_retrieved(client):
    answer = payload(await client.post("/api/assistant/ask", json={"question": "馆长的生日是哪天"}))
    assert answer["grounded"] is False
    assert answer["sources"] == []
    assert answer["answer"] == NO_ANSWER


async def test_an_answer_can_be_scoped_to_a_single_book(client):
    first = await make_book(client, title="分布式系统", summary="讲解一致性与复制。", isbn=None)
    second = await make_book(client, title="操作系统导论", summary="讲解进程调度与虚拟内存。", isbn=None)
    payload(await client.post(f"/api/rag/books/{first['id']}/index"))
    payload(await client.post(f"/api/rag/books/{second['id']}/index"))

    answer = payload(await client.post("/api/assistant/ask", json={
        "question": "这本书讲什么", "book_id": first["id"]}))
    assert {s["book_id"] for s in answer["sources"]} == {first["id"]}


async def test_a_blank_question_is_rejected_by_the_request_model(client):
    assert (await client.post("/api/assistant/ask", json={"question": ""})).status_code == 422


# --- 会话 -------------------------------------------------------------


async def test_a_session_records_both_turns_with_their_sources(client):
    await _seed_policy(client)
    session = payload(await client.post("/api/assistant/sessions", json={"title": "借阅咨询"}))
    answer = payload(await client.post(
        f"/api/assistant/sessions/{session['id']}/ask", json={"question": "续借几次"}))
    assert answer["session_id"] == session["id"]

    messages = payload(await client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "续借几次"
    assert messages[1]["sources"][0]["doc_title"] == "借阅规则"


async def test_turns_accumulate_across_questions(client):
    await _seed_policy(client)
    session = payload(await client.post("/api/assistant/sessions", json={}))
    for question in ("借期多久", "逾期怎么罚", "VIP 能借几册"):
        payload(await client.post(f"/api/assistant/sessions/{session['id']}/ask", json={"question": question}))

    messages = payload(await client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert len(messages) == 6


async def test_sessions_are_listed_per_reader(client):
    from app.testing import make_reader

    reader = await make_reader(client)
    payload(await client.post("/api/assistant/sessions", json={"reader_id": reader["id"], "title": "我的"}))
    payload(await client.post("/api/assistant/sessions", json={"title": "匿名"}))

    assert payload(await client.get("/api/assistant/sessions"))["total"] == 2
    mine = payload(await client.get("/api/assistant/sessions", params={"reader_id": reader["id"]}))
    assert mine["total"] == 1
    assert mine["records"][0]["title"] == "我的"


async def test_deleting_a_session_takes_its_messages(client):
    await _seed_policy(client)
    session = payload(await client.post("/api/assistant/sessions", json={}))
    payload(await client.post(f"/api/assistant/sessions/{session['id']}/ask", json={"question": "借期多久"}))

    payload(await client.delete(f"/api/assistant/sessions/{session['id']}"))
    code, _ = failure(await client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert code == 404


async def test_asking_in_a_missing_session(client):
    code, _ = failure(await client.post("/api/assistant/sessions/cs_nope/ask", json={"question": "在吗"}))
    assert code == 404
