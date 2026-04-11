from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_inputs import _PreparedProductionOrderInputs


@dataclass(frozen=True)
class _InputsUnpackApplicationResult:
    bundle_type_ids: list[int]
    recipe_colors_by_bundle: dict[int, set[int]]
    all_recipe_color_ids: list[int]
    sku_by_color_size: dict[tuple[int, int], object]
    color_to_sizes: dict[int, list[int]]
    size_ids: list[int]
    size_weights_source: str
    size_weights: dict[int, float]
    stock_by_color_size: dict[tuple[int, int], int]
    current_stock_by_color_size: dict[tuple[int, int], int]
    in_flight_source: str
    in_flight_raw_qty_total: int
    in_flight_effective_qty_total: int
    in_flight_effective_lines: int
    in_flight_effective_by_color_size: dict[tuple[int, int], int]
    in_flight_eta_days_by_color_size: dict[tuple[int, int], int]
    demand_by_bundle: dict[int, float]
    total_daily_sales: float
    bundle_stock_source: str
    ready_bundle_stock_total: int
    shares_by_bundle: dict[int, float]


def _apply_production_order_inputs_unpack(
    *,
    inputs_application: _PreparedProductionOrderInputs,
) -> _InputsUnpackApplicationResult:
    return _InputsUnpackApplicationResult(
        bundle_type_ids=inputs_application.bundle_type_ids,
        recipe_colors_by_bundle=inputs_application.recipe_colors_by_bundle,
        all_recipe_color_ids=inputs_application.all_recipe_color_ids,
        sku_by_color_size=inputs_application.sku_by_color_size,
        color_to_sizes=inputs_application.color_to_sizes,
        size_ids=inputs_application.size_ids,
        size_weights_source=inputs_application.size_weights_source,
        size_weights=inputs_application.size_weights,
        stock_by_color_size=inputs_application.stock_by_color_size,
        current_stock_by_color_size=inputs_application.current_stock_by_color_size,
        in_flight_source=inputs_application.in_flight_source,
        in_flight_raw_qty_total=inputs_application.in_flight_raw_qty_total,
        in_flight_effective_qty_total=inputs_application.in_flight_effective_qty_total,
        in_flight_effective_lines=inputs_application.in_flight_effective_lines,
        in_flight_effective_by_color_size=inputs_application.in_flight_effective_by_color_size,
        in_flight_eta_days_by_color_size=inputs_application.in_flight_eta_days_by_color_size,
        demand_by_bundle=inputs_application.demand_by_bundle,
        total_daily_sales=inputs_application.total_daily_sales,
        bundle_stock_source=inputs_application.bundle_stock_source,
        ready_bundle_stock_total=inputs_application.ready_bundle_stock_total,
        shares_by_bundle=inputs_application.shares_by_bundle,
    )
