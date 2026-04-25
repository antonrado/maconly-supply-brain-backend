from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    model_config = ConfigDict(from_attributes=True)


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
    items: list[PurchaseOrderItemRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


PositiveArticleId = Annotated[int, Field(ge=1)]


class PurchaseOrderFromProposalRequest(BaseModel):
    article_id: int | None = Field(default=None, ge=1)
    article_ids: list[PositiveArticleId] | None = None
    target_date: date
    comment: str | None = None
    explanation: bool = True

    @model_validator(mode="after")
    def validate_article_scope(self) -> PurchaseOrderFromProposalRequest:
        if self.article_id is not None and self.article_ids is not None:
            raise ValueError("Use either article_id or article_ids, not both.")
        return self
