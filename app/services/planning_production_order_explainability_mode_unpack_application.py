from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderExplanationBlock
from app.services.planning_production_order_explainability_mode_application import (
    _ExplainabilityModeApplicationResult,
)


@dataclass(frozen=True)
class _ExplainabilityModeUnpackApplicationResult:
    explanation: ProductionOrderExplanationBlock


def _apply_production_order_explainability_mode_unpack(
    *,
    explainability_mode_application: _ExplainabilityModeApplicationResult,
) -> _ExplainabilityModeUnpackApplicationResult:
    return _ExplainabilityModeUnpackApplicationResult(
        explanation=explainability_mode_application.explanation,
    )
