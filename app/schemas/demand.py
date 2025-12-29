from __future__ import annotations

from pydantic import BaseModel


class DemandResult(BaseModel):
    article_id: int
    avg_daily_sales: float
    forecast_demand: float
    current_stock: int
    coverage_days: float
    deficit: int
    target_coverage_days: int
    observation_window_days: int
    forecast_horizon_days: int
    explanation: str | None = None
