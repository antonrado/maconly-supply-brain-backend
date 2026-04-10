from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer1_summary_application import (
    _Layer1SummaryApplicationResult,
)


@dataclass(frozen=True)
class _Layer1SummaryUnpackApplicationResult:
    layer1_avg_coverage_days: float
    layer1_high_stockout_risk_count: int
    layer1_contract: dict[str, object]


def _apply_production_order_layer1_summary_unpack(
    *,
    layer1_summary_application: _Layer1SummaryApplicationResult,
) -> _Layer1SummaryUnpackApplicationResult:
    return _Layer1SummaryUnpackApplicationResult(
        layer1_avg_coverage_days=layer1_summary_application.layer1_avg_coverage_days,
        layer1_high_stockout_risk_count=layer1_summary_application.layer1_high_stockout_risk_count,
        layer1_contract=layer1_summary_application.layer1_contract,
    )
