from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer4_application import (
    _Layer4ApplicationResult,
)


@dataclass(frozen=True)
class _Layer4UnpackApplicationResult:
    expected_horizon_sales: float
    layer4_scenarios: list[dict[str, str | int | float]]
    capital_gap_summary: dict[str, float | str | None]
    layer4_contract: dict[str, str | bool | list[str] | dict[str, bool]]
    layer4_aggregate_deltas: dict[str, dict[str, float]]


def _apply_production_order_layer4_unpack(
    *,
    layer4_application: _Layer4ApplicationResult,
) -> _Layer4UnpackApplicationResult:
    return _Layer4UnpackApplicationResult(
        expected_horizon_sales=layer4_application.expected_horizon_sales,
        layer4_scenarios=layer4_application.layer4_scenarios,
        capital_gap_summary=layer4_application.capital_gap_summary,
        layer4_contract=layer4_application.layer4_contract,
        layer4_aggregate_deltas=layer4_application.layer4_aggregate_deltas,
    )
