from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer4ApplicationResult:
    expected_horizon_sales: float
    layer4_scenarios: list[dict[str, str | int | float]]
    capital_gap_summary: dict[str, float | str | None]
    layer4_contract: dict[str, str | bool | list[str] | dict[str, bool]]
    layer4_aggregate_deltas: dict[str, dict[str, float]]


def _apply_production_order_layer4_analysis(
    *,
    candidate_total_units: int,
    planning_horizon_days: int,
    available_bundles_for_cover: int,
    total_daily_sales: float,
    reorder_point_days: int,
    layer3_purchase_shaping: dict[str, int],
    available_capital: float | None,
    unit_capital_per_unit: float,
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    average_realized_price_main: float,
    average_realized_price_assorti: float,
    capital_cost_rate: float,
    stockout_penalty_weight: float,
    overstock_penalty_weight: float,
    build_layer4_scenarios: Callable[..., list[dict[str, str | int | float]]],
    build_capital_gap_summary: Callable[..., dict[str, float | str | None]],
    build_layer4_contract_summary: Callable[..., dict[str, str | bool | list[str] | dict[str, bool]]],
    build_layer4_aggregate_deltas: Callable[..., dict[str, dict[str, float]]],
) -> _Layer4ApplicationResult:
    expected_horizon_sales = total_daily_sales * planning_horizon_days
    layer4_scenarios = build_layer4_scenarios(
        base_purchase_units=candidate_total_units,
        available_bundles_for_cover=available_bundles_for_cover,
        total_daily_sales=total_daily_sales,
        reorder_point_days=reorder_point_days,
        expected_horizon_sales=expected_horizon_sales,
        layer3_purchase_shaping=layer3_purchase_shaping,
        unit_capital_per_unit=unit_capital_per_unit,
        margin_main_per_unit=margin_main_per_unit,
        margin_assorti_per_unit=margin_assorti_per_unit,
        average_realized_price_main=average_realized_price_main,
        average_realized_price_assorti=average_realized_price_assorti,
        capital_cost_rate=capital_cost_rate,
        stockout_penalty_weight=stockout_penalty_weight,
        overstock_penalty_weight=overstock_penalty_weight,
    )
    capital_gap_summary = build_capital_gap_summary(
        layer4_scenarios=layer4_scenarios,
        available_capital=available_capital,
    )
    layer4_contract = build_layer4_contract_summary(layer4_scenarios)
    layer4_aggregate_deltas = build_layer4_aggregate_deltas(layer4_scenarios)

    return _Layer4ApplicationResult(
        expected_horizon_sales=expected_horizon_sales,
        layer4_scenarios=layer4_scenarios,
        capital_gap_summary=capital_gap_summary,
        layer4_contract=layer4_contract,
        layer4_aggregate_deltas=layer4_aggregate_deltas,
    )
