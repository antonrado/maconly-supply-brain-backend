from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class PurchaseOrderItemBase(BaseModel):
    article_id: int
    color_id: int
    size_id: int
    quantity: int
    source: str = "auto"
    notes: str | None = None


class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass


class PurchaseOrderItemUpdate(BaseModel):
    quantity: int | None = None
    source: str | None = None
    notes: str | None = None


class PurchaseOrderItemRead(PurchaseOrderItemBase):
    id: int
    purchase_order_id: int

    class Config:
        orm_mode = True


class PurchaseOrderBase(BaseModel):
    status: str = "draft"
    target_date: date
    comment: str | None = None
    external_ref: str | None = None


class PurchaseOrderCreate(PurchaseOrderBase):
    pass


class PurchaseOrderUpdate(BaseModel):
    status: str | None = None
    comment: str | None = None
    external_ref: str | None = None


class PurchaseOrderRead(PurchaseOrderBase):
    id: int
    created_at: datetime
    updated_at: datetime
    items: list[PurchaseOrderItemRead] = []

    class Config:
        orm_mode = True


class PurchaseOrderFromProposalRequest(BaseModel):
    target_date: date
    comment: str | None = None
    explanation: bool = True
