from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .wb_replenishment import WbReplenishmentRequest, WbReplenishmentItem


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


class WbShipmentProposalComparisonRequest(WbReplenishmentRequest):
    pass


class WbShipmentProposalLineComparison(BaseModel):
    article_id: int
    color_id: int | None
    size_id: int | None
    replenishment_recommended_qty: int
    canonical_recommended_qty: int
    divergence_category: Literal["aligned", "replenishment_only_line", "canonical_only_line", "qty_mismatch"]
    explanation: str


class WbShipmentProposalArticleComparison(BaseModel):
    article_id: int
    replenishment_total_recommended_qty: int
    replenishment_line_count: int
    canonical_status: Literal["ok", "blocked"]
    canonical_action: Literal["wait", "order_with_buffer", "order_minimum_only"] | None = None
    canonical_total_units: int | None = None
    canonical_risk_level: Literal["ok", "warning", "critical", "overstock", "no_data"] | None = None
    canonical_arrival_projection_status: Literal["safe_cover_until_arrival", "shortage_before_arrival", "no_demand"] | None = None
    canonical_blocker_code: str | None = None
    divergence_category: Literal[
        "aligned",
        "canonical_blocked",
        "canonical_wait_vs_replenishment_qty",
        "replenishment_only_qty",
        "canonical_only_qty",
        "qty_mismatch_constraints",
        "qty_mismatch_decision_policy",
        "qty_mismatch",
    ]
    explanation: str
    line_comparisons: list[WbShipmentProposalLineComparison] = Field(default_factory=list)


class WbShipmentProposalComparisonScopeNormalization(BaseModel):
    requested_article_ids: list[int] | None = None
    normalized_article_ids: list[int] = Field(default_factory=list)
    normalization_strategy: Literal["requested_article_ids", "replenishment_output_article_ids"]
    comparison_as_of_date: date
    canonical_planning_horizon_days: int
    notes: list[str] = Field(default_factory=list)


class WbShipmentProposalComparisonSummary(BaseModel):
    has_divergence: bool
    article_count: int
    divergent_article_count: int
    categories: dict[str, int] = Field(default_factory=dict)


class WbShipmentProposalComparisonResponse(BaseModel):
    target_date: date
    wb_arrival_date: date
    replenishment_items: list[WbReplenishmentItem] = Field(default_factory=list)
    scope_normalization: WbShipmentProposalComparisonScopeNormalization
    article_comparisons: list[WbShipmentProposalArticleComparison] = Field(default_factory=list)
    divergence_summary: WbShipmentProposalComparisonSummary


class WbShipmentUpdate(BaseModel):
    status: str | None = None
    comment: str | None = None


class WbShipmentRead(WbShipmentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    items: list[WbShipmentItemRead] = Field(default_factory=list)

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

    model_config = ConfigDict(from_attributes=True)


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
    recent_shipments: list[WbShipmentRecentHeader] = Field(default_factory=list)

    # Volume aggregates
    avg_total_final_qty_last3: float | None = None
    last_shipment_total_final_qty: int | None = None

    # Comment template and explanation
    default_comment_template: str | None = None
    explanation: str | None = None
