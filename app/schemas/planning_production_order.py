from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class BundleDemandInput(BaseModel):
    bundle_type_id: int = Field(..., ge=1)
    daily_sales: float = Field(..., ge=0)


class BundleStockInput(BaseModel):
    bundle_type_id: int = Field(..., ge=1)
    wb_qty: int = Field(0, ge=0)
    local_qty: int = Field(0, ge=0)


class InFlightSupplyInput(BaseModel):
    article_id: int = Field(..., ge=1)
    color_id: int = Field(..., ge=1)
    size_id: int = Field(..., ge=1)
    qty: int = Field(..., ge=1)
    eta_days: int = Field(..., ge=0)
    stage: Literal["production", "china_to_nsk", "packaging", "nsk_to_wb", "other"] = "other"


class LeadTimeDaysInput(BaseModel):
    production: int | None = Field(default=None, ge=0)
    china_to_nsk: int | None = Field(default=None, ge=0)
    packaging: int | None = Field(default=None, ge=0)
    nsk_to_wb: int | None = Field(default=None, ge=0)


class PlanningOverridesInput(BaseModel):
    target_coverage_days: int | None = Field(default=None, ge=1, le=365)
    service_level_percent: int | None = Field(default=None, ge=1, le=100)
    alert_threshold_days: int | None = Field(default=None, ge=1, le=365)
    lead_time_days: LeadTimeDaysInput | None = None
    fabric_min_batch_qty_default: int | None = Field(default=None, ge=0)
    elastic_min_batch_qty_default: int | None = Field(default=None, ge=0)
    allow_order_with_buffer: bool = True


class ProductionOrderProposalRequest(BaseModel):
    article_id: int = Field(..., ge=1)
    planning_horizon_days: int = Field(90, ge=1, le=365)
    bundle_daily_sales: list[BundleDemandInput] = Field(default_factory=list)
    bundle_stock: list[BundleStockInput] = Field(default_factory=list)
    in_flight_supply: list[InFlightSupplyInput] = Field(default_factory=list)
    size_weights: dict[int, float] = Field(default_factory=dict)
    overrides: PlanningOverridesInput | None = None

    @field_validator("bundle_daily_sales")
    @classmethod
    def validate_bundle_daily_sales(cls, value: list[BundleDemandInput]) -> list[BundleDemandInput]:
        if not value:
            raise ValueError("bundle_daily_sales must not be empty")

        seen: set[int] = set()
        for item in value:
            if item.bundle_type_id in seen:
                raise ValueError("bundle_daily_sales contains duplicate bundle_type_id")
            seen.add(item.bundle_type_id)

        return value

    @field_validator("bundle_stock")
    @classmethod
    def validate_bundle_stock(cls, value: list[BundleStockInput]) -> list[BundleStockInput]:
        seen: set[int] = set()
        for item in value:
            if item.bundle_type_id in seen:
                raise ValueError("bundle_stock contains duplicate bundle_type_id")
            seen.add(item.bundle_type_id)
        return value

    @field_validator("size_weights")
    @classmethod
    def validate_size_weights(cls, value: dict[int, float]) -> dict[int, float]:
        for size_id, weight in value.items():
            if size_id < 1:
                raise ValueError("size_weights keys must be positive size IDs")
            if weight <= 0:
                raise ValueError("size_weights values must be positive")
        return value


class ProductionOrderProposalFromWbRequest(BaseModel):
    article_id: int = Field(..., ge=1)
    planning_horizon_days: int = Field(90, ge=1, le=365)
    observation_window_days: int = Field(30, ge=1, le=365)
    as_of_date: date | None = None
    freshness_mode: Literal["warn", "strict"] = "warn"
    freshness_sales_stale_after_days: int | None = Field(default=None, ge=0, le=3650)
    freshness_stock_stale_after_days: int | None = Field(default=None, ge=0, le=3650)
    bundle_type_ids: list[int] = Field(default_factory=list)
    in_flight_supply: list[InFlightSupplyInput] = Field(default_factory=list)
    size_weights: dict[int, float] = Field(default_factory=dict)
    overrides: PlanningOverridesInput | None = None

    @field_validator("bundle_type_ids")
    @classmethod
    def validate_bundle_type_ids(cls, value: list[int]) -> list[int]:
        seen: set[int] = set()
        for bundle_type_id in value:
            if bundle_type_id < 1:
                raise ValueError("bundle_type_ids must contain positive values")
            if bundle_type_id in seen:
                raise ValueError("bundle_type_ids contains duplicates")
            seen.add(bundle_type_id)
        return value

    @field_validator("size_weights")
    @classmethod
    def validate_size_weights(cls, value: dict[int, float]) -> dict[int, float]:
        for size_id, weight in value.items():
            if size_id < 1:
                raise ValueError("size_weights keys must be positive size IDs")
            if weight <= 0:
                raise ValueError("size_weights values must be positive")
        return value


class ProductionOrderRecommendationLine(BaseModel):
    article_id: int
    color_id: int
    size_id: int
    recommended_qty: int
    source_reason: str


class ProductionOrderRecommendation(BaseModel):
    action: Literal["wait", "order_with_buffer", "order_minimum_only"]
    priority: int
    target_arrival_date: date
    total_units: int
    lines: list[ProductionOrderRecommendationLine]


class FabricConstraintApplied(BaseModel):
    pantone_code: str
    required: int
    applied_min: int


class ElasticConstraintApplied(BaseModel):
    article_id: int
    elastic_type_id: int | None
    required: int
    applied_min: int


class ProductionOrderConstraintsApplied(BaseModel):
    fabric_min_batches: list[FabricConstraintApplied] = Field(default_factory=list)
    elastic_min_batches: list[ElasticConstraintApplied] = Field(default_factory=list)


class ProductionOrderAlternative(BaseModel):
    action: Literal["wait", "order_with_buffer", "order_minimum_only"]
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class ProductionOrderExplanationBlock(BaseModel):
    summary: str
    steps: list[str]
    meta: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderProposalResponse(BaseModel):
    status: Literal["ok", "skipped"]
    article_id: int
    generated_at: datetime
    risk_level: Literal["ok", "warning", "critical", "overstock", "no_data"]
    days_of_cover_estimate: float
    lead_time_days_total: int
    recommendation: ProductionOrderRecommendation | None
    constraints_applied: ProductionOrderConstraintsApplied
    alternatives: list[ProductionOrderAlternative]
    explanation: ProductionOrderExplanationBlock
