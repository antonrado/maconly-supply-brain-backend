from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer2_summary_application import (
    _Layer2SummaryApplicationResult,
)


@dataclass(frozen=True)
class _Layer2SummaryUnpackApplicationResult:
    layer2_contract: dict[str, object]
    layer2_decision_quality: dict[str, object]


def _apply_production_order_layer2_summary_unpack(
    *,
    layer2_summary_application: _Layer2SummaryApplicationResult,
) -> _Layer2SummaryUnpackApplicationResult:
    return _Layer2SummaryUnpackApplicationResult(
        layer2_contract=layer2_summary_application.layer2_contract,
        layer2_decision_quality=layer2_summary_application.layer2_decision_quality,
    )
