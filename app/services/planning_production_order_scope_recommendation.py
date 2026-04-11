from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.schemas.planning_production_order import (
    ProductionOrderAlternative,
    ProductionOrderArrivalProjection,
    ProductionOrderPhysicalScope,
    ProductionOrderRecommendation,
    ProductionOrderRecommendationLine,
)


@dataclass(frozen=True)
class _ScopeRecommendationResult:
    physical_scope: ProductionOrderPhysicalScope
    arrival_projection: ProductionOrderArrivalProjection
    action: str
    recommendation: ProductionOrderRecommendation
    alternatives: list[ProductionOrderAlternative]


def _apply_production_order_scope_and_recommendation(
    *,
    bundle_stock_source: str,
    in_flight_source: str,
    size_weights_source: str,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    current_stock_by_color_size: dict[tuple[int, int], int],
    in_flight_effective_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
    ready_bundle_stock_total: int,
    total_daily_sales: float,
    lead_time_days_total: int,
    risk_level: str,
    candidate_total_units: int,
    allow_order_with_buffer: bool,
    priority: int,
    now: datetime,
    candidate_lines: list[ProductionOrderRecommendationLine],
    estimate_raw_bundle_stock: Callable[..., int],
    build_physical_scope_and_arrival_projection: Callable[..., tuple[ProductionOrderPhysicalScope, ProductionOrderArrivalProjection]],
    build_recommendation_and_alternatives: Callable[..., tuple[str, ProductionOrderRecommendation, list[ProductionOrderAlternative]]],
) -> _ScopeRecommendationResult:
    physical_scope, arrival_projection = build_physical_scope_and_arrival_projection(
        bundle_stock_source=bundle_stock_source,
        in_flight_source=in_flight_source,
        size_weights_source=size_weights_source,
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        current_stock_by_color_size=current_stock_by_color_size,
        in_flight_effective_by_color_size=in_flight_effective_by_color_size,
        shares_by_bundle=shares_by_bundle,
        ready_bundle_stock_total=ready_bundle_stock_total,
        total_daily_sales=total_daily_sales,
        lead_time_days_total=lead_time_days_total,
        estimate_raw_bundle_stock=estimate_raw_bundle_stock,
    )
    action, recommendation, alternatives = build_recommendation_and_alternatives(
        arrival_projection=arrival_projection,
        total_daily_sales=total_daily_sales,
        risk_level=risk_level,
        candidate_total_units=candidate_total_units,
        allow_order_with_buffer=allow_order_with_buffer,
        priority=priority,
        lead_time_days_total=lead_time_days_total,
        now=now,
        candidate_lines=candidate_lines,
    )

    return _ScopeRecommendationResult(
        physical_scope=physical_scope,
        arrival_projection=arrival_projection,
        action=action,
        recommendation=recommendation,
        alternatives=alternatives,
    )
