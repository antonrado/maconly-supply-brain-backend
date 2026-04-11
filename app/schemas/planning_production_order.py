from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    layer3_stockout_boost_max: float | None = Field(default=None, ge=0, le=1)
    layer3_overstock_dampen_max: float | None = Field(default=None, ge=0, le=1)
    layer5_unavoidable_stockout_risk_threshold: float | None = Field(default=None, ge=0, le=1)
    layer5_accelerate_production_risk_threshold: float | None = Field(default=None, ge=0, le=1)
    layer2_capital_cost_rate: float | None = Field(default=None, ge=0, le=1)
    layer2_stockout_penalty_weight: float | None = Field(default=None, ge=0, le=1)
    layer2_overstock_penalty_weight: float | None = Field(default=None, ge=0, le=1)
    layer5_accelerate_action_cost_rate: float | None = Field(default=None, ge=0, le=1)
    layer5_price_slowdown_lost_volume_rate: float | None = Field(default=None, ge=0, le=1)
    layer5_reduce_order_marginal_profit_rate: float | None = Field(default=None, ge=0, le=1)
    production_cost_per_unit: float | None = Field(default=None, ge=0)
    logistics_cost_per_unit: float | None = Field(default=None, ge=0)
    wb_commission_percent_main: float | None = Field(default=None, ge=0, le=1)
    wb_commission_percent_assorti: float | None = Field(default=None, ge=0, le=1)
    average_realized_price_main: float | None = Field(default=None, ge=0)
    average_realized_price_assorti: float | None = Field(default=None, ge=0)
    available_capital: float | None = Field(default=None, ge=0)
    capital_governance_mode: Literal["strict", "safe_default"] = "strict"
    allow_order_with_buffer: bool = True

    @model_validator(mode="after")
    def validate_layer5_threshold_order(self) -> "PlanningOverridesInput":
        unavoidable_threshold = self.layer5_unavoidable_stockout_risk_threshold
        accelerate_threshold = self.layer5_accelerate_production_risk_threshold
        if (
            unavoidable_threshold is not None
            and accelerate_threshold is not None
            and accelerate_threshold < unavoidable_threshold
        ):
            raise ValueError(
                "layer5_accelerate_production_risk_threshold must be greater than or equal to "
                "layer5_unavoidable_stockout_risk_threshold"
            )
        return self


class ProductionOrderProposalRequest(BaseModel):
    article_id: int = Field(..., ge=1)
    planning_horizon_days: int = Field(90, ge=1, le=365)
    explainability_mode: Literal["full", "compact"] = "full"
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
    explainability_mode: Literal["full", "compact"] = "full"
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
    shared_pool_required: int | None = None
    sibling_proxy_required: int = 0


class ElasticConstraintApplied(BaseModel):
    article_id: int
    elastic_type_id: int | None
    required: int
    applied_min: int


class ResourceAllocationBundleReservation(BaseModel):
    bundle_type_id: int
    reserved_qty: int
    share_weight: float
    allocation_basis: Literal["single_consumer", "demand_share"]


class ResourceAllocationReservation(BaseModel):
    color_id: int
    size_id: int
    stock_qty: int
    total_reserved_qty: int
    shared_resource: bool
    consumer_bundle_type_ids: list[int] = Field(default_factory=list)
    allocations: list[ResourceAllocationBundleReservation] = Field(default_factory=list)


class ProductionOrderResourceAllocationApplied(BaseModel):
    mode: Literal["per_article_bundle_competition"]
    total_resource_keys: int
    competing_resource_keys: int
    fully_reserved_resource_keys: int
    total_stock_units: int
    total_reserved_units: int
    reserved_bundle_units: dict[int, int] = Field(default_factory=dict)
    reservations: list[ResourceAllocationReservation] = Field(default_factory=list)
    contract: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderConstraintsApplied(BaseModel):
    fabric_min_batches: list[FabricConstraintApplied] = Field(default_factory=list)
    elastic_min_batches: list[ElasticConstraintApplied] = Field(default_factory=list)
    resource_allocation: ProductionOrderResourceAllocationApplied | None = None


class ProductionOrderAlternative(BaseModel):
    action: Literal["wait", "order_with_buffer", "order_minimum_only"]
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class ProductionOrderExplanationBlock(BaseModel):
    summary: str
    steps: list[str]
    meta: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderPhysicalScope(BaseModel):
    local_stock_scope: Literal["all_warehouses_merged", "warehouse_filtered"]
    wb_stock_scope: Literal["article_wb_mapping_bundle_stock_aggregated", "request_explicit_bundle_stock"]
    ready_bundle_source: str
    raw_single_source: Literal["stock_balance_by_sku_unit_recipe_projection"]
    nsc_assembled_bundle_inventory_state: Literal["not_persisted"]
    warnings: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderArrivalProjection(BaseModel):
    status: Literal["safe_cover_until_arrival", "shortage_before_arrival", "no_demand"]
    arrival_horizon_days: int
    demand_units_until_arrival: int
    ready_bundle_units_now: int
    raw_bundle_capacity_now: int
    in_flight_bundle_capacity_at_arrival: int
    projected_supply_units_before_arrival: int
    projected_availability_at_arrival: int
    projected_shortage_before_arrival: int
    projected_cover_days_at_arrival: float | None = None
    basis: dict[str, Any] = Field(default_factory=dict)


class ProductionOrderProposalResponse(BaseModel):
    status: Literal["ok", "skipped"]
    article_id: int
    generated_at: datetime
    risk_level: Literal["ok", "warning", "critical", "overstock", "no_data"]
    days_of_cover_estimate: float
    lead_time_days_total: int
    recommendation: ProductionOrderRecommendation | None
    constraints_applied: ProductionOrderConstraintsApplied
    physical_scope: ProductionOrderPhysicalScope | None = None
    arrival_projection: ProductionOrderArrivalProjection | None = None
    alternatives: list[ProductionOrderAlternative]
    explanation: ProductionOrderExplanationBlock
