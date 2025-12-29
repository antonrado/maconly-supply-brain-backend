from __future__ import annotations

from pydantic import BaseModel


class OrderProposalReason(BaseModel):
    article_id: int
    article_code: str

    color_id: int | None
    color_name: str | None

    elastic_type_id: int | None
    elastic_type_name: str | None

    proposed_qty: int

    base_deficit: int
    strictness: float
    adjusted_deficit: float

    min_fabric_batch: int | None
    min_elastic_batch: int | None
    color_min_batch: int | None

    total_available_before: int
    forecast_horizon_days: int | None

    final_order_qty: int
    limiting_constraint: str | None

    explanation: str


class ArticleOrderExplanation(BaseModel):
    article_id: int
    article_code: str
    reasons: list[OrderProposalReason]


class OrderExplanationPortfolioResponse(BaseModel):
    items: list[ArticleOrderExplanation]
