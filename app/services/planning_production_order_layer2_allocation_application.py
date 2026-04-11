from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer2AllocationApplicationResult:
    layer2_allocation_decisions: list[dict[str, int | float | str]]
    layer2_allocation_summary: dict[str, int]


def _apply_production_order_layer2_allocation(
    *,
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    lead_time_days_total: int,
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    unit_capital_per_unit: float,
    capital_cost_rate: float,
    stockout_penalty_weight: float,
    overstock_penalty_weight: float,
    build_layer2_allocation_decisions: Callable[
        ..., tuple[list[dict[str, int | float | str]], dict[str, int]]
    ],
) -> _Layer2AllocationApplicationResult:
    layer2_allocation_decisions, layer2_allocation_summary = (
        build_layer2_allocation_decisions(
            stock_health_metrics=layer1_stock_health_metrics,
            lead_time_days_total=lead_time_days_total,
            margin_main_per_unit=margin_main_per_unit,
            margin_assorti_per_unit=margin_assorti_per_unit,
            unit_capital_per_unit=unit_capital_per_unit,
            capital_cost_rate=capital_cost_rate,
            stockout_penalty_weight=stockout_penalty_weight,
            overstock_penalty_weight=overstock_penalty_weight,
        )
    )
    return _Layer2AllocationApplicationResult(
        layer2_allocation_decisions=layer2_allocation_decisions,
        layer2_allocation_summary=layer2_allocation_summary,
    )
