from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer2SummaryApplicationResult:
    layer2_contract: dict[str, object]
    layer2_decision_quality: dict[str, object]


def _apply_production_order_layer2_summary(
    *,
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    layer2_allocation_summary: dict[str, int],
    build_layer2_contract_summary: Callable[..., dict[str, object]],
    build_layer2_decision_quality_summary: Callable[..., dict[str, object]],
) -> _Layer2SummaryApplicationResult:
    layer2_contract = build_layer2_contract_summary(
        layer2_allocation_decisions=layer2_allocation_decisions,
        layer2_allocation_summary=layer2_allocation_summary,
    )
    layer2_decision_quality = build_layer2_decision_quality_summary(
        layer2_allocation_decisions=layer2_allocation_decisions,
    )
    return _Layer2SummaryApplicationResult(
        layer2_contract=layer2_contract,
        layer2_decision_quality=layer2_decision_quality,
    )
