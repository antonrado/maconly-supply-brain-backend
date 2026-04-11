from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer1SummaryApplicationResult:
    layer1_avg_coverage_days: float
    layer1_high_stockout_risk_count: int
    layer1_contract: dict[str, object]


def _apply_production_order_layer1_summary(
    *,
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    layer1_high_stockout_risk_threshold: float,
    build_layer1_contract_summary: Callable[
        [list[dict[str, int | float | None]]], dict[str, object]
    ],
) -> _Layer1SummaryApplicationResult:
    layer1_avg_coverage_days = (
        round(
            sum(float(item["coverage_days"]) for item in layer1_stock_health_metrics)
            / len(layer1_stock_health_metrics),
            2,
        )
        if layer1_stock_health_metrics
        else 0.0
    )
    layer1_high_stockout_risk_count = sum(
        1
        for item in layer1_stock_health_metrics
        if float(item["stockout_risk"]) >= layer1_high_stockout_risk_threshold
    )
    layer1_contract = build_layer1_contract_summary(layer1_stock_health_metrics)
    return _Layer1SummaryApplicationResult(
        layer1_avg_coverage_days=layer1_avg_coverage_days,
        layer1_high_stockout_risk_count=layer1_high_stockout_risk_count,
        layer1_contract=layer1_contract,
    )
