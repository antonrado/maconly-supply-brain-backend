from datetime import date

from pydantic import BaseModel


class OrderProposalItem(BaseModel):
    article_id: int
    color_id: int
    size_id: int
    quantity: int
    explanation: str | None = None


class OrderProposalResponse(BaseModel):
    target_date: date
    items: list[OrderProposalItem]
    global_explanation: str | None = None
