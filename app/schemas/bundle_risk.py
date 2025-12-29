from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class BundleRiskLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    OVERSTOCK = "overstock"
    NO_DATA = "no_data"


class ArticleBundleRiskEntry(BaseModel):
    article_id: int
    article_code: str
    bundle_type_id: int
    bundle_type_name: str

    avg_daily_sales: float | None
    total_available_bundles: int
    days_of_cover: float | None

    risk_level: BundleRiskLevel
    safety_stock_days: int | None
    alert_threshold_days: int | None
    overstock_threshold_days: int | None

    explanation: str


class BundleRiskPortfolioResponse(BaseModel):
    items: list[ArticleBundleRiskEntry]
