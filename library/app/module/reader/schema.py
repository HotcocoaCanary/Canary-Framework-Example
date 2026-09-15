"""Request and response models for readers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateReaderRequest(BaseModel):
    name: str = Field(max_length=100, description="姓名")
    card_no: str | None = Field(default=None, max_length=32, description="借书证号，留空自动生成")
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    level: str = Field(default="normal", description="student / normal / vip / staff")


class UpdateReaderRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    level: str | None = Field(default=None, description="student / normal / vip / staff")
    status: str | None = Field(default=None, description="active / suspended")


class ReaderResponse(BaseModel):
    id: str
    card_no: str
    name: str
    email: str | None = None
    phone: str | None = None
    level: str
    status: str
    fine_balance_cents: int = 0
    max_loans: int = Field(default=0, description="该等级的可借上限")
    active_loans: int = Field(default=0, description="当前在借数量")
    overdue_loans: int = Field(default=0, description="当前逾期数量")
    created_at: datetime
    updated_at: datetime


class PayFineRequest(BaseModel):
    amount_cents: int = Field(gt=0, description="缴纳金额（分）")
