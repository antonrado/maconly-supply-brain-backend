from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _RiskApplicationResult:
    days_of_cover_estimate: float
    risk_level: str


def _apply_production_order_risk_level(
    *,
    total_daily_sales: float,
    available_bundles_for_cover: int,
    reorder_point_days: int,
    alert_threshold_days: int,
    target_coverage_days: int,
) -> _RiskApplicationResult:
    if total_daily_sales <= 0:
        return _RiskApplicationResult(
            days_of_cover_estimate=9999.0,
            risk_level="no_data",
        )

    days_of_cover_estimate = available_bundles_for_cover / total_daily_sales
    if days_of_cover_estimate < reorder_point_days:
        risk_level = "critical"
    elif days_of_cover_estimate < alert_threshold_days:
        risk_level = "warning"
    elif days_of_cover_estimate > target_coverage_days * 2:
        risk_level = "overstock"
    else:
        risk_level = "ok"

    return _RiskApplicationResult(
        days_of_cover_estimate=days_of_cover_estimate,
        risk_level=risk_level,
    )
