from __future__ import annotations

from pydantic import BaseModel


class MonitoringTopRiskItem(BaseModel):
    article_id: int
    article_code: str
    bundle_type_id: int | None = None
    bundle_type_name: str | None = None

    risk_level: str

    days_of_cover: float | None = None
    final_order_qty: int | None = None


class MonitoringTopRiskResponse(BaseModel):
    items: list[MonitoringTopRiskItem]
