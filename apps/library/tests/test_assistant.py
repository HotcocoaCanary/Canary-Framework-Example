"""The librarian assistant — grounded answers, citations and conversation state."""

from __future__ import annotations

from app.infra.ai import NO_ANSWER
from app.testing import failure, make_book, payload

POLICY = (
    "普通读者一次最多可借 5 册，借期 30 天，可续借 2 次。"
    "逾期每天每册罚款 0.5 元。VIP 读者借期为 60 天，最多可借 10 册。"
)


def _seed_policy(client) -> dict:
    return payload(client.post("/api/rag/documents", json={
        "title": "借阅规则", "text": POLICY, "source": "policy"}))


def test_an_answer_cites_the_passages_it_used(client):
    _seed_policy(client)
    answer = payload(client.post("/api/assistant/ask", json={"question": "普通读者可以借几册"}))

    assert answer["grounded"] is True
    assert answer["sources"]
    assert answer["sources"][0]["doc_title"] == "借阅规则"
    assert "5 册" in answer["answer"]


def test_the_assistant_refuses_when_nothing_is_retrieved(client):
    answer = payload(client.post("/api/assistant/ask", json={"question": "馆长的生日是哪天"}))
    assert answer["grounded"] is False
    assert answer["sources"] == []
    assert answer["answer"] == NO_ANSWER


def test_an_answer_can_be_scoped_to_a_single_book(client):
    first = make_book(client, title="分布式系统", summary="讲解一致性与复制。", isbn=None)
    second = make_book(client, title="操作系统导论", summary="讲解进程调度与虚拟内存。", isbn=None)
    payload(client.post(f"/api/rag/books/{first['id']}/index"))
    payload(client.post(f"/api/rag/books/{second['id']}/index"))

    answer = payload(client.post("/api/assistant/ask", json={
        "question": "这本书讲什么", "book_id": first["id"]}))
    assert {s["book_id"] for s in answer["sources"]} == {first["id"]}


def test_a_blank_question_is_rejected_by_the_request_model(client):
    assert client.post("/api/assistant/ask", json={"question": ""}).status_code == 422


# --- 会话 -------------------------------------------------------------


def test_a_session_records_both_turns_with_their_sources(client):
    _seed_policy(client)
    session = payload(client.post("/api/assistant/sessions", json={"title": "借阅咨询"}))
    answer = payload(client.post(
        f"/api/assistant/sessions/{session['id']}/ask", json={"question": "续借几次"}))
    assert answer["session_id"] == session["id"]

    messages = payload(client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "续借几次"
    assert messages[1]["sources"][0]["doc_title"] == "借阅规则"


def test_turns_accumulate_across_questions(client):
    _seed_policy(client)
    session = payload(client.post("/api/assistant/sessions", json={}))
    for question in ("借期多久", "逾期怎么罚", "VIP 能借几册"):
        payload(client.post(f"/api/assistant/sessions/{session['id']}/ask", json={"question": question}))

    messages = payload(client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert len(messages) == 6


def test_sessions_are_listed_per_reader(client):
    from app.testing import make_reader

    reader = make_reader(client)
    payload(client.post("/api/assistant/sessions", json={"reader_id": reader["id"], "title": "我的"}))
    payload(client.post("/api/assistant/sessions", json={"title": "匿名"}))

    assert payload(client.get("/api/assistant/sessions"))["total"] == 2
    mine = payload(client.get("/api/assistant/sessions", params={"reader_id": reader["id"]}))
    assert mine["total"] == 1
    assert mine["records"][0]["title"] == "我的"


def test_deleting_a_session_takes_its_messages(client):
    _seed_policy(client)
    session = payload(client.post("/api/assistant/sessions", json={}))
    payload(client.post(f"/api/assistant/sessions/{session['id']}/ask", json={"question": "借期多久"}))

    payload(client.delete(f"/api/assistant/sessions/{session['id']}"))
    code, _ = failure(client.get(f"/api/assistant/sessions/{session['id']}/messages"))
    assert code == 404


def test_asking_in_a_missing_session(client):
    code, _ = failure(client.post("/api/assistant/sessions/cs_nope/ask", json={"question": "在吗"}))
    assert code == 404
