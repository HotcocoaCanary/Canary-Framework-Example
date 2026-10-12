"""Catalogue — bibliographic records and the holdings attached to them."""

from __future__ import annotations

from app.testing import failure, make_book, payload


async def test_create_book_with_copies_reports_holdings(client):
    book = await make_book(client, copies=3)
    assert book["holdings"] == {
        "total": 3,
        "available": 3,
        "on_loan": 0,
        "unavailable": 0,
        "reservations": 0,
    }


async def test_duplicate_isbn_is_rejected(client):
    await make_book(client, isbn="9787111000001")
    code, msg = failure(await client.post("/api/catalog/books", json={
        "title": "另一本", "author": "李四", "isbn": "9787111000001"}))
    assert code == 409
    assert "已存在" in msg


async def test_search_matches_title_author_and_isbn(client):
    await make_book(client, title="深入理解计算机系统", author="Bryant", isbn="9787111111111")
    await make_book(client, title="数据库系统概念", author="Silberschatz", category="计算机")
    await make_book(client, title="唐诗三百首", author="蘅塘退士", category="文学")

    assert payload(await client.get("/api/catalog/books", params={"keyword": "计算机"}))["total"] == 1
    assert payload(await client.get("/api/catalog/books", params={"keyword": "Silberschatz"}))["total"] == 1
    assert payload(await client.get("/api/catalog/books", params={"keyword": "9787111111111"}))["total"] == 1
    assert payload(await client.get("/api/catalog/books", params={"category": "文学"}))["total"] == 1


async def test_search_pages(client):
    for index in range(5):
        await make_book(client, title=f"馆藏图书 {index}", isbn=None)
    page = payload(await client.get("/api/catalog/books", params={"page": 2, "size": 2}))
    assert page["total"] == 5
    assert page["pages"] == 3
    assert page["current"] == 2
    assert len(page["records"]) == 2


async def test_get_missing_book_is_a_404_code(client):
    code, msg = failure(await client.get("/api/catalog/books/bk_nope"))
    assert code == 404
    assert "不存在" in msg


async def test_update_book_changes_only_supplied_fields(client):
    book = await make_book(client, publisher="机械工业出版社")
    updated = payload(await client.patch(f"/api/catalog/books/{book['id']}", json={"category": "教材"}))
    assert updated["category"] == "教材"
    assert updated["publisher"] == "机械工业出版社"
    assert updated["title"] == book["title"]


async def test_update_with_no_fields_is_rejected(client):
    book = await make_book(client)
    code, _ = failure(await client.patch(f"/api/catalog/books/{book['id']}", json={}))
    assert code == 422


async def test_add_copies_and_list_them(client):
    book = await make_book(client, copies=1)
    added = payload(await client.post(
        f"/api/catalog/books/{book['id']}/copies", json={"count": 2, "location": "分馆"}))
    assert len(added) == 2
    assert {c["location"] for c in added} == {"分馆"}

    copies = payload(await client.get(f"/api/catalog/books/{book['id']}/copies"))
    assert len(copies) == 3
    assert len({c["barcode"] for c in copies}) == 3


async def test_copy_can_be_marked_repairing_but_not_on_loan(client):
    book = await make_book(client, copies=1)
    copy = payload(await client.get(f"/api/catalog/books/{book['id']}/copies"))[0]

    repairing = payload(await client.patch(f"/api/catalog/copies/{copy['id']}", json={"status": "repairing"}))
    assert repairing["status"] == "repairing"

    code, msg = failure(await client.patch(f"/api/catalog/copies/{copy['id']}", json={"status": "on_loan"}))
    assert code == 422
    assert "借还流程" in msg


async def test_repairing_copy_is_not_counted_as_available(client):
    book = await make_book(client, copies=2)
    copy = payload(await client.get(f"/api/catalog/books/{book['id']}/copies"))[0]
    await client.patch(f"/api/catalog/copies/{copy['id']}", json={"status": "lost"})

    holdings = payload(await client.get(f"/api/catalog/books/{book['id']}"))["holdings"]
    assert holdings == {
        "total": 2, "available": 1, "on_loan": 0, "unavailable": 1, "reservations": 0}


async def test_delete_book_refused_while_a_copy_is_out(client):
    from app.testing import make_reader

    book = await make_book(client, copies=1)
    reader = await make_reader(client)
    payload(await client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": book["id"]}))

    code, msg = failure(await client.delete(f"/api/catalog/books/{book['id']}"))
    assert code == 409
    assert "在借" in msg


async def test_delete_book_removes_its_holdings_and_corpus(client):
    book = await make_book(client, copies=2, summary="讲解一致性与复制的经典教材。")
    payload(await client.post(f"/api/rag/books/{book['id']}/index"))

    payload(await client.delete(f"/api/catalog/books/{book['id']}"))
    failure(await client.get(f"/api/catalog/books/{book['id']}"))
    assert payload(await client.get("/api/rag/documents", params={"book_id": book["id"]}))["total"] == 0


async def test_categories_group_the_shelf(client):
    await make_book(client, category="计算机", isbn=None)
    await make_book(client, category="计算机", isbn=None)
    await make_book(client, category="文学", isbn=None)
    counts = {row["category"]: row["books"] for row in payload(await client.get("/api/catalog/categories"))}
    assert counts == {"计算机": 2, "文学": 1}
