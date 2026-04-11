from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_horizon_application import (
    _HorizonApplicationResult,
)


@dataclass(frozen=True)
class _HorizonUnpackApplicationResult:
    economic_buffer_days: int
    target_bundle_horizon_days: int
    required_bundle_units: int
    bundle_deficit_total: int


def _apply_production_order_horizon_unpack(
    *,
    horizon_application: _HorizonApplicationResult,
) -> _HorizonUnpackApplicationResult:
    return _HorizonUnpackApplicationResult(
        economic_buffer_days=horizon_application.economic_buffer_days,
        target_bundle_horizon_days=horizon_application.target_bundle_horizon_days,
        required_bundle_units=horizon_application.required_bundle_units,
        bundle_deficit_total=horizon_application.bundle_deficit_total,
    )
