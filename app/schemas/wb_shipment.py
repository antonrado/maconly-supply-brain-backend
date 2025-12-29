from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from .wb_replenishment import WbReplenishmentRequest


class WbShipmentItemBase(BaseModel):
    article_id: int
    color_id: int
    size_id: int
    wb_sku: str | None
    recommended_qty: int
    final_qty: int
    nsk_stock_available: int
    oos_risk_before: str
    oos_risk_after: str
    limited_by_nsk_stock: bool
    limited_by_max_coverage: bool
    ignored_due_to_zero_sales: bool
    below_min_coverage_threshold: bool
    article_total_deficit: int
    article_total_recommended: int
    explanation: str | None = None


class WbShipmentItemUpdate(BaseModel):
    final_qty: int | None = None
    explanation: str | None = None


class WbShipmentItemRead(WbShipmentItemBase):
    id: int
    shipment_id: int

    model_config = ConfigDict(from_attributes=True)


class WbShipmentItemSummary(BaseModel):
    item_id: int
    shipment_id: int

    article_id: int
    color_id: int
    size_id: int
    wb_sku: str | None

    recommended_qty: int
    final_qty: int
    nsk_stock_available: int

    oos_risk_before: str
    oos_risk_after: str

    limited_by_nsk_stock: bool
    limited_by_max_coverage: bool
    ignored_due_to_zero_sales: bool
    below_min_coverage_threshold: bool

    article_total_deficit: int
    article_total_recommended: int

    explanation: str | None = None


class WbShipmentBase(BaseModel):
    status: str = "draft"
    target_date: date
    wb_arrival_date: date
    comment: str | None = None
    strategy: str
    zero_sales_policy: str
    target_coverage_days: int
    min_coverage_days: int
    max_coverage_days_after: int
    max_replenishment_per_article: int | None = None


class WbShipmentCreate(WbReplenishmentRequest):
    comment: str


class WbShipmentUpdate(BaseModel):
    status: str | None = None
    comment: str | None = None


class WbShipmentRead(WbShipmentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    items: list[WbShipmentItemRead] = []

    model_config = ConfigDict(from_attributes=True)


class WbShipmentHeaderRead(BaseModel):
    id: int
    status: str
    target_date: date
    wb_arrival_date: date
    comment: str | None
    created_at: datetime
    updated_at: datetime

    total_final_qty: int
    total_items: int
    red_risk_count: int
    yellow_risk_count: int

    class Config:
        orm_mode = True


class WbShipmentAggregates(BaseModel):
    shipment_id: int
    status: str
    created_at: datetime
    updated_at: datetime

    total_items: int
    total_final_qty: int
    red_risk_count: int
    yellow_risk_count: int


class WbShipmentRecentHeader(BaseModel):
    id: int
    status: str
    target_date: date
    wb_arrival_date: date
    created_at: datetime
    updated_at: datetime

    total_final_qty: int
    total_items: int


class WbShipmentPresetResponse(BaseModel):
    # Base dates
    target_date: date
    suggested_wb_arrival_date: date

    # Suggested strategy and zero-sales handling
    suggested_strategy: str
    suggested_zero_sales_policy: str

    suggested_target_coverage_days: int
    suggested_min_coverage_days: int
    suggested_max_coverage_days_after: int
    suggested_max_replenishment_per_article: int | None

    # Recent shipments
    recent_shipments: list[WbShipmentRecentHeader] = []

    # Volume aggregates
    avg_total_final_qty_last3: float | None = None
    last_shipment_total_final_qty: int | None = None

    # Comment template and explanation
    default_comment_template: str | None = None
    explanation: str | None = None
