from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class WbReplenishmentRequest(BaseModel):
    target_date: date
    wb_arrival_date: date
    target_coverage_days: int = 30
    min_coverage_days: int = 7
    replenishment_strategy: str = "normal"
    zero_sales_policy: str = "ignore"
    max_coverage_days_after: int = 60
    max_replenishment_per_article: int | None = None
    article_ids: list[int] | None = None
    explanation: bool = True


class WbReplenishmentItem(BaseModel):
    article_id: int
    article_code: str | None

    color_id: int | None
    color_inner_code: str | None

    size_id: int | None
    size_label: str | None

    wb_sku: str | None

    wb_stock_total: int
    avg_daily_sales_30d: float
    coverage_days_current: float

    days_until_arrival: int
    target_coverage_days: int
    projected_stock_at_arrival: int
    projected_coverage_at_arrival: float

    recommended_qty: int
    coverage_after_transfer: float

    nsk_stock_available: int
    nsk_stock_after_transfer: int

    oos_risk_before: str
    oos_risk_after: str

    limited_by_nsk_stock: bool
    limited_by_max_coverage: bool
    ignored_due_to_zero_sales: bool
    below_min_coverage_threshold: bool

    article_total_deficit: int
    article_total_recommended: int

    explanation: str | None = None


class WbReplenishmentResponse(BaseModel):
    target_date: date
    wb_arrival_date: date
    items: list[WbReplenishmentItem]
