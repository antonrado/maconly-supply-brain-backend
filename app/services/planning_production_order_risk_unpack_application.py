from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_risk_application import (
    _RiskApplicationResult,
)


@dataclass(frozen=True)
class _RiskUnpackApplicationResult:
    days_of_cover_estimate: float
    risk_level: str


def _apply_production_order_risk_unpack(
    *,
    risk_application: _RiskApplicationResult,
) -> _RiskUnpackApplicationResult:
    return _RiskUnpackApplicationResult(
        days_of_cover_estimate=risk_application.days_of_cover_estimate,
        risk_level=risk_application.risk_level,
    )
