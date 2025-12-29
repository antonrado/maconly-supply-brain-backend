from __future__ import annotations

from pydantic import BaseModel

from app.schemas.bundle_risk import ArticleBundleRiskEntry
from app.schemas.order_explanation import ArticleOrderExplanation
from app.schemas.planning_health import ArticleHealthSummary


class ArticleDashboardResponse(BaseModel):
    article_id: int
    article_code: str | None = None

    bundle_type_id: int | None = None
    bundle_type_name: str | None = None

    risk: ArticleBundleRiskEntry | None = None
    order: ArticleOrderExplanation | None = None
    health: ArticleHealthSummary | None = None
