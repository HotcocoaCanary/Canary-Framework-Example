"""Request and response models for circulation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BorrowRequest(BaseModel):
    """Identify the reader, then the item — by copy, by barcode, or by title."""

    reader_id: str = Field(description="读者 ID 或借书证号")
    book_id: Optional[str] = Field(default=None, description="书目 ID：自动挑一册可借副本")
    copy_id: Optional[str] = Field(default=None, description="指定副本 ID")
    barcode: Optional[str] = Field(default=None, description="扫码借阅：副本条码")

    # 「三选一」的校验放在 service 而不是 pydantic validator：Canary 0.9.2 渲染
    # 校验错误时会把 ctx 里的原始 ValueError 直接塞进 JSONResponse，导致 422 响应
    # 本身 500（见 doc/bug/003-validation-error-response-crashes.md）。


class ReturnRequest(BaseModel):
    copy_id: Optional[str] = Field(default=None, description="副本 ID")
    barcode: Optional[str] = Field(default=None, description="副本条码")


class LoanResponse(BaseModel):
    id: str
    copy_id: str
    book_id: str
    book_title: Optional[str] = None
    barcode: Optional[str] = None
    reader_id: str
    borrowed_at: datetime
    due_at: datetime
    returned_at: Optional[datetime] = None
    renew_count: int = 0
    status: str
    fine_cents: int = 0
    overdue_days: int = Field(default=0, description="已逾期天数（未还时为当前逾期）")


class ReturnReceipt(BaseModel):
    loan: LoanResponse
    fine_cents: int = Field(default=0, description="本次产生的逾期罚金（分）")
    reader_fine_balance_cents: int = Field(default=0, description="读者累计欠款（分）")
    next_reservation_ready: bool = Field(
        default=False, description="该书是否已为下一位预约读者留存"
    )


class ReserveRequest(BaseModel):
    reader_id: str = Field(description="读者 ID 或借书证号")
    book_id: str = Field(description="书目 ID")


class ReservationResponse(BaseModel):
    id: str
    book_id: str
    book_title: Optional[str] = None
    reader_id: str
    status: str
    queue_position: Optional[int] = Field(default=None, description="排队位次（waiting 时有效）")
    copy_id: Optional[str] = None
    created_at: datetime
    ready_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
