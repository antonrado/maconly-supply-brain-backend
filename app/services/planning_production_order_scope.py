from __future__ import annotations

from math import ceil
from typing import Callable

from app.schemas.planning_production_order import (
    ProductionOrderArrivalProjection,
    ProductionOrderPhysicalScope,
)

# Ownership: this module owns physical-scope and arrival-horizon projection builders.

EstimateRawBundleStock = Callable[..., dict[int, int]]


def _build_physical_scope_contract(
    *,
    bundle_stock_source: str,
    in_flight_source: str,
    size_weights_source: str,
) -> ProductionOrderPhysicalScope:
    wb_stock_scope = (
        "article_wb_mapping_bundle_stock_aggregated"
        if bundle_stock_source in {"wb_defaults", "none"}
        else "request_explicit_bundle_stock"
    )
    warnings = [
        "assembled_nsc_bundles_not_separately_persisted",
    ]
    assumptions = {
        "size_weights_source": size_weights_source,
        "in_flight_source": in_flight_source,
        "bundle_stock_source": bundle_stock_source,
        "ready_bundle_formula": "sum(bundle_stock.wb_qty + bundle_stock.local_qty)",
        "raw_bundle_capacity_method": "competition_aware_recipe_projection",
        "raw_bundle_capacity_counts_in_main_cover_model": True,
        "nsc_assembled_bundle_inventory_state": "not_persisted",
    }
    return ProductionOrderPhysicalScope(
        local_stock_scope="all_warehouses_merged",
        wb_stock_scope=wb_stock_scope,
        ready_bundle_source=bundle_stock_source,
        raw_single_source="stock_balance_by_sku_unit_recipe_projection",
        nsc_assembled_bundle_inventory_state="not_persisted",
        warnings=warnings,
        assumptions=assumptions,
    )


def _build_arrival_horizon_projection(
    *,
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
    estimate_raw_bundle_stock: EstimateRawBundleStock,
) -> ProductionOrderArrivalProjection:
    raw_now_by_bundle = estimate_raw_bundle_stock(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        stock_by_color_size=current_stock_by_color_size,
        shares_by_bundle=shares_by_bundle,
    )
    in_flight_by_bundle = estimate_raw_bundle_stock(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        stock_by_color_size=in_flight_effective_by_color_size,
        shares_by_bundle=shares_by_bundle,
    )
    raw_bundle_capacity_now = sum(raw_now_by_bundle.values())
    in_flight_bundle_capacity_at_arrival = sum(in_flight_by_bundle.values())
    demand_units_until_arrival = int(
        ceil(max(float(total_daily_sales), 0.0) * max(int(lead_time_days_total), 0))
    )
    projected_supply_units_before_arrival = (
        int(ready_bundle_stock_total)
        + int(raw_bundle_capacity_now)
        + int(in_flight_bundle_capacity_at_arrival)
    )
    projected_shortage_before_arrival = max(
        int(demand_units_until_arrival) - int(projected_supply_units_before_arrival),
        0,
    )
    projected_availability_at_arrival = max(
        int(projected_supply_units_before_arrival) - int(demand_units_until_arrival),
        0,
    )

    if total_daily_sales <= 0:
        status = "no_demand"
        projected_cover_days_at_arrival = None
    else:
        status = (
            "shortage_before_arrival"
            if projected_shortage_before_arrival > 0
            else "safe_cover_until_arrival"
        )
        projected_cover_days_at_arrival = round(
            float(projected_availability_at_arrival) / float(total_daily_sales),
            4,
        )

    return ProductionOrderArrivalProjection(
        status=status,
        arrival_horizon_days=max(int(lead_time_days_total), 0),
        demand_units_until_arrival=int(demand_units_until_arrival),
        ready_bundle_units_now=int(ready_bundle_stock_total),
        raw_bundle_capacity_now=int(raw_bundle_capacity_now),
        in_flight_bundle_capacity_at_arrival=int(in_flight_bundle_capacity_at_arrival),
        projected_supply_units_before_arrival=int(projected_supply_units_before_arrival),
        projected_availability_at_arrival=int(projected_availability_at_arrival),
        projected_shortage_before_arrival=int(projected_shortage_before_arrival),
        projected_cover_days_at_arrival=projected_cover_days_at_arrival,
        basis={
            "demand_basis": "daily_sales_x_lead_time_days_total",
            "raw_bundle_treatment": "counted_as_convertible_before_arrival",
            "bundle_state_note": "raw_bundle_capacity_is_recipe_projection_not_persisted_ready_inventory",
            "ready_bundle_units_now": int(ready_bundle_stock_total),
            "raw_bundle_capacity_now_by_bundle": {
                int(bundle_type_id): int(raw_now_by_bundle.get(bundle_type_id, 0))
                for bundle_type_id in bundle_type_ids
            },
            "in_flight_bundle_capacity_at_arrival_by_bundle": {
                int(bundle_type_id): int(in_flight_by_bundle.get(bundle_type_id, 0))
                for bundle_type_id in bundle_type_ids
            },
        },
    )


def build_physical_scope_and_arrival_projection(
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
    estimate_raw_bundle_stock: EstimateRawBundleStock,
) -> tuple[ProductionOrderPhysicalScope, ProductionOrderArrivalProjection]:
    physical_scope = _build_physical_scope_contract(
        bundle_stock_source=bundle_stock_source,
        in_flight_source=in_flight_source,
        size_weights_source=size_weights_source,
    )
    arrival_projection = _build_arrival_horizon_projection(
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
    return physical_scope, arrival_projection
