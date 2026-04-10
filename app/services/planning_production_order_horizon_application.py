from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _HorizonApplicationResult:
    economic_buffer_days: int
    target_bundle_horizon_days: int
    required_bundle_units: int
    bundle_deficit_total: int


def _apply_production_order_horizon(
    *,
    risk_level: str,
    allow_order_with_buffer: bool,
    total_daily_sales: float,
    lead_time_days_total: int,
    days_of_cover_estimate: float,
    target_coverage_days: int,
    safety_stock_days: int,
    available_bundles_for_cover: int,
    compute_economic_buffer_days: Callable[..., int],
    ceil_to_int: Callable[[float], int],
) -> _HorizonApplicationResult:
    economic_buffer_days = compute_economic_buffer_days(
        risk_level=risk_level,
        allow_order_with_buffer=allow_order_with_buffer,
        total_daily_sales=total_daily_sales,
        lead_time_days_total=lead_time_days_total,
        days_of_cover_estimate=days_of_cover_estimate,
        ceil_to_int=ceil_to_int,
    )
    target_bundle_horizon_days = (
        target_coverage_days
        + lead_time_days_total
        + safety_stock_days
        + economic_buffer_days
    )
    required_bundle_units = ceil_to_int(total_daily_sales * target_bundle_horizon_days)
    bundle_deficit_total = max(required_bundle_units - available_bundles_for_cover, 0)
    return _HorizonApplicationResult(
        economic_buffer_days=economic_buffer_days,
        target_bundle_horizon_days=target_bundle_horizon_days,
        required_bundle_units=required_bundle_units,
        bundle_deficit_total=bundle_deficit_total,
    )
