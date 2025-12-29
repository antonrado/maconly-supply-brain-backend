from __future__ import annotations

from pydantic import BaseModel

from app.schemas.bundle_risk import BundleRiskLevel


class ArticleHealthSummary(BaseModel):
    article_id: int
    article_code: str

    worst_risk_level: BundleRiskLevel | None
    worst_risk_bundle_type_id: int | None
    worst_risk_bundle_type_name: str | None
    days_of_cover: float | None
    avg_daily_sales: float | None
    total_available_bundles: int | None

    total_final_order_qty: int
    dominant_limiting_constraint: str | None

    has_critical: bool
    has_warning: bool


class PlanningHealthPortfolioResponse(BaseModel):
    items: list[ArticleHealthSummary]
