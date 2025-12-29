from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class WbWarehouseStockItem(BaseModel):
    warehouse_id: int | None
    warehouse_name: str | None
    stock_qty: int


class WbManagerSkuStats(BaseModel):
    # SKU identification
    article_id: int
    article_code: str

    color_id: int
    color_inner_code: str

    size_id: int
    size_label: str

    wb_sku: str | None

    # WB stock
    wb_stock_total: int
    wb_stock_by_warehouse: list[WbWarehouseStockItem]

    # Observation window
    observation_window_days: int

    # Sales over periods
    sales_1d: int
    sales_7d: int
    sales_30d: int

    # Averages and forecast
    avg_daily_sales_30d: float
    forecast_7d: float
    forecast_30d: float

    # Coverage and OOS risk
    coverage_days: float
    oos_risk_level: str

    # Explanation
    explanation: str | None = None


class WbManagerOnlineResponse(BaseModel):
    target_date: date
    items: list[WbManagerSkuStats]
