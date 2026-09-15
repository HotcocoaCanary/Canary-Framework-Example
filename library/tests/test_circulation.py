"""Circulation — the loan desk rules: borrow, return, renew, reserve."""

from __future__ import annotations

from app.testing import failure, make_book, make_overdue, make_reader, payload


def _borrow(client, reader, book) -> dict:
    return payload(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": book["id"]}))


# --- 借书 -------------------------------------------------------------


def test_borrow_marks_the_copy_on_loan(client):
    book = make_book(client, copies=2)
    reader = make_reader(client)

    loan = _borrow(client, reader, book)
    assert loan["status"] == "active"
    assert loan["book_title"] == book["title"]
    assert loan["due_at"] > loan["borrowed_at"]

    holdings = payload(client.get(f"/api/catalog/books/{book['id']}"))["holdings"]
    assert holdings["available"] == 1
    assert holdings["on_loan"] == 1


def test_borrow_by_barcode(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    copy = payload(client.get(f"/api/catalog/books/{book['id']}/copies"))[0]

    loan = payload(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "barcode": copy["barcode"]}))
    assert loan["copy_id"] == copy["id"]


def test_borrow_accepts_a_library_card_number(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = payload(client.post("/api/circulation/borrow", json={
        "reader_id": reader["card_no"], "book_id": book["id"]}))
    assert loan["reader_id"] == reader["id"]


def test_borrow_needs_at_least_one_target(client):
    reader = make_reader(client)
    code, msg = failure(client.post("/api/circulation/borrow", json={"reader_id": reader["id"]}))
    assert code == 422
    assert "至少提供一个" in msg


def test_borrow_a_copy_that_is_already_out(client):
    book = make_book(client, copies=1)
    first, second = make_reader(client), make_reader(client, name="李四")
    _borrow(client, first, book)

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": second["id"], "book_id": book["id"]}))
    assert code == 409
    assert "全部副本已借出" in msg


def test_borrow_a_title_with_no_holdings(client):
    book = make_book(client, copies=0)
    reader = make_reader(client)
    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": book["id"]}))
    assert code == 404
    assert "暂无馆藏" in msg


def test_loan_limit_is_enforced_per_level(client):
    reader = make_reader(client, level="normal")  # 上限 5 册
    books = [make_book(client, title=f"书 {i}", copies=1, isbn=None) for i in range(6)]
    for book in books[:5]:
        _borrow(client, reader, book)

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": books[5]["id"]}))
    assert code == 409
    assert "上限" in msg


def test_suspended_reader_cannot_borrow(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    payload(client.patch(f"/api/readers/{reader['id']}", json={"status": "suspended"}))

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": book["id"]}))
    assert code == 409
    assert "停用" in msg


def test_an_overdue_loan_blocks_further_borrowing(client):
    first, second = make_book(client, copies=1, isbn=None), make_book(client, title="第二本", copies=1, isbn=None)
    reader = make_reader(client)
    loan = _borrow(client, reader, first)
    make_overdue(client, loan["id"], days=10)

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": second["id"]}))
    assert code == 409
    assert "逾期" in msg


def test_unpaid_fines_past_the_threshold_block_borrowing(client):
    first, second = make_book(client, copies=1, isbn=None), make_book(client, title="第二本", copies=1, isbn=None)
    reader = make_reader(client)
    loan = _borrow(client, reader, first)
    make_overdue(client, loan["id"], days=45)  # 45 天 × 50 分 = 2250 分，超过 2000 分停借线
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": reader["id"], "book_id": second["id"]}))
    assert code == 409
    assert "停借线" in msg


# --- 还书 -------------------------------------------------------------


def test_return_on_time_charges_nothing(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)

    receipt = payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))
    assert receipt["fine_cents"] == 0
    assert receipt["loan"]["status"] == "returned"
    assert receipt["next_reservation_ready"] is False
    assert payload(client.get(f"/api/catalog/books/{book['id']}"))["holdings"]["available"] == 1


def test_overdue_return_charges_the_reader(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    make_overdue(client, loan["id"], days=4)

    receipt = payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))
    assert receipt["fine_cents"] == 4 * 50
    assert receipt["reader_fine_balance_cents"] == 4 * 50
    assert receipt["loan"]["overdue_days"] == 4
    assert payload(client.get(f"/api/readers/{reader['id']}"))["fine_balance_cents"] == 200


def test_returning_a_copy_nobody_borrowed(client):
    book = make_book(client, copies=1)
    copy = payload(client.get(f"/api/catalog/books/{book['id']}/copies"))[0]
    code, msg = failure(client.post("/api/circulation/return", json={"copy_id": copy["id"]}))
    assert code == 409
    assert "没有在借记录" in msg


def test_paying_a_fine_reduces_the_balance(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    make_overdue(client, loan["id"], days=4)
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))

    after = payload(client.post(f"/api/readers/{reader['id']}/fines/payment", json={"amount_cents": 150}))
    assert after["fine_balance_cents"] == 50

    code, _ = failure(client.post(f"/api/readers/{reader['id']}/fines/payment", json={"amount_cents": 999}))
    assert code == 422


# --- 续借 -------------------------------------------------------------


def test_renew_extends_the_due_date(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)

    renewed = payload(client.post(f"/api/circulation/loans/{loan['id']}/renew"))
    assert renewed["renew_count"] == 1
    assert renewed["due_at"] > loan["due_at"]


def test_renew_is_capped(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    payload(client.post(f"/api/circulation/loans/{loan['id']}/renew"))
    payload(client.post(f"/api/circulation/loans/{loan['id']}/renew"))

    code, msg = failure(client.post(f"/api/circulation/loans/{loan['id']}/renew"))
    assert code == 409
    assert "上限" in msg


def test_overdue_loans_cannot_be_renewed(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    make_overdue(client, loan["id"], days=1)

    code, msg = failure(client.post(f"/api/circulation/loans/{loan['id']}/renew"))
    assert code == 409
    assert "已逾期" in msg


def test_a_reservation_blocks_renewal(client):
    book = make_book(client, copies=1)
    holder, waiter = make_reader(client), make_reader(client, name="李四")
    loan = _borrow(client, holder, book)
    payload(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))

    code, msg = failure(client.post(f"/api/circulation/loans/{loan['id']}/renew"))
    assert code == 409
    assert "预约" in msg


# --- 预约 -------------------------------------------------------------


def test_reserving_a_book_that_is_on_the_shelf_is_pointless(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    code, msg = failure(client.post("/api/circulation/reservations", json={
        "reader_id": reader["id"], "book_id": book["id"]}))
    assert code == 409
    assert "直接借阅" in msg


def test_reservation_queue_is_first_come_first_served(client):
    book = make_book(client, copies=1)
    holder, first, second = (
        make_reader(client), make_reader(client, name="李四"), make_reader(client, name="王五"))
    loan = _borrow(client, holder, book)

    one = payload(client.post("/api/circulation/reservations", json={
        "reader_id": first["id"], "book_id": book["id"]}))
    two = payload(client.post("/api/circulation/reservations", json={
        "reader_id": second["id"], "book_id": book["id"]}))
    assert one["queue_position"] == 1
    assert two["queue_position"] == 2

    receipt = payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))
    assert receipt["next_reservation_ready"] is True

    mine = payload(client.get(f"/api/circulation/readers/{first['id']}/reservations"))["records"]
    assert mine[0]["status"] == "ready"
    assert mine[0]["copy_id"] == loan["copy_id"]


def test_a_held_copy_is_not_lent_to_anyone_else(client):
    book = make_book(client, copies=1)
    holder, waiter, outsider = (
        make_reader(client), make_reader(client, name="李四"), make_reader(client, name="王五"))
    loan = _borrow(client, holder, book)
    payload(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))

    code, msg = failure(client.post("/api/circulation/borrow", json={
        "reader_id": outsider["id"], "copy_id": loan["copy_id"]}))
    assert code == 409
    assert "预留" in msg


def test_the_reserving_reader_can_collect_the_held_copy(client):
    book = make_book(client, copies=1)
    holder, waiter = make_reader(client), make_reader(client, name="李四")
    loan = _borrow(client, holder, book)
    payload(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))

    collected = payload(client.post("/api/circulation/borrow", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))
    assert collected["copy_id"] == loan["copy_id"]

    mine = payload(client.get(f"/api/circulation/readers/{waiter['id']}/reservations"))["records"]
    assert mine[0]["status"] == "fulfilled"


def test_duplicate_reservations_are_rejected(client):
    book = make_book(client, copies=1)
    holder, waiter = make_reader(client), make_reader(client, name="李四")
    _borrow(client, holder, book)
    payload(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))

    code, msg = failure(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))
    assert code == 409
    assert "重复" in msg


def test_cancelling_a_ready_reservation_shelves_the_copy(client):
    book = make_book(client, copies=1)
    holder, waiter = make_reader(client), make_reader(client, name="李四")
    loan = _borrow(client, holder, book)
    reservation = payload(client.post("/api/circulation/reservations", json={
        "reader_id": waiter["id"], "book_id": book["id"]}))
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))

    payload(client.delete(f"/api/circulation/reservations/{reservation['id']}"))
    assert payload(client.get(f"/api/catalog/books/{book['id']}"))["holdings"]["available"] == 1


# --- 查询 -------------------------------------------------------------


def test_overdue_report_lists_only_late_loans(client):
    late_book = make_book(client, title="逾期的书", copies=1, isbn=None)
    fine_book = make_book(client, title="正常的书", copies=1, isbn=None)
    reader, other = make_reader(client), make_reader(client, name="李四")
    late = _borrow(client, reader, late_book)
    _borrow(client, other, fine_book)
    make_overdue(client, late["id"], days=3)

    page = payload(client.get("/api/circulation/overdue"))
    assert page["total"] == 1
    assert page["records"][0]["id"] == late["id"]
    assert page["records"][0]["overdue_days"] == 3


def test_reader_history_includes_returned_loans(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    payload(client.post("/api/circulation/return", json={"copy_id": loan["copy_id"]}))
    _borrow(client, reader, book)

    page = payload(client.get(f"/api/circulation/readers/{reader['id']}/loans"))
    assert page["total"] == 2
    assert {r["status"] for r in page["records"]} == {"active", "returned"}


def test_reader_counters_track_active_and_overdue(client):
    book = make_book(client, copies=1)
    reader = make_reader(client)
    loan = _borrow(client, reader, book)
    make_overdue(client, loan["id"], days=2)

    profile = payload(client.get(f"/api/readers/{reader['id']}"))
    assert profile["active_loans"] == 1
    assert profile["overdue_loans"] == 1
    assert profile["max_loans"] == 5
