from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderExplanationBlock


@dataclass(frozen=True)
class _ExplainabilityModeApplicationResult:
    explanation: ProductionOrderExplanationBlock


def _apply_production_order_explainability_mode(
    *,
    explanation: ProductionOrderExplanationBlock,
    mode: str,
    apply_explainability_mode: Callable[[ProductionOrderExplanationBlock, str], ProductionOrderExplanationBlock],
) -> _ExplainabilityModeApplicationResult:
    explanation = apply_explainability_mode(
        explanation,
        mode,
    )
    return _ExplainabilityModeApplicationResult(explanation=explanation)
