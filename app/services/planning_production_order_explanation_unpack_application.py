from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderExplanationBlock
from app.services.planning_production_order_explanation_application import (
    _ExplanationApplicationResult,
)


@dataclass(frozen=True)
class _ExplanationUnpackApplicationResult:
    explanation: ProductionOrderExplanationBlock


def _apply_production_order_explanation_unpack(
    *,
    explanation_application: _ExplanationApplicationResult,
) -> _ExplanationUnpackApplicationResult:
    return _ExplanationUnpackApplicationResult(
        explanation=explanation_application.explanation,
    )
