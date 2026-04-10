from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.services.planning_production_order_explainability_mode_application import (
    _ExplainabilityModeApplicationResult,
)
from app.services.planning_production_order_response_application import (
    _ResponseApplicationResult,
)
from app.schemas.planning_production_order import (
    ProductionOrderConstraintsApplied,
    ProductionOrderExplanationBlock,
    ProductionOrderProposalResponse,
)


@dataclass(frozen=True)
class _SkipApplicationResult:
    response: ProductionOrderProposalResponse


def _apply_production_order_skip(
    *,
    article_id: int,
    generated_at: datetime,
    lead_time_days_total: int,
    explainability_mode: str,
    apply_production_order_explainability_mode: Callable[
        ..., _ExplainabilityModeApplicationResult
    ],
    apply_explainability_mode: Callable[
        [ProductionOrderExplanationBlock, str], ProductionOrderExplanationBlock
    ],
    apply_production_order_response: Callable[..., _ResponseApplicationResult],
) -> _SkipApplicationResult:
    explainability_mode_application = apply_production_order_explainability_mode(
        explanation=ProductionOrderExplanationBlock(
            summary="Артикул исключен из планирования настройкой include_in_planning=false.",
            steps=[
                "Получены настройки статьи и проверен флаг include_in_planning.",
                "Расчет пропущен по явному правилу исключения.",
            ],
        ),
        mode=explainability_mode,
        apply_explainability_mode=apply_explainability_mode,
    )
    response_application = apply_production_order_response(
        status="skipped",
        article_id=article_id,
        generated_at=generated_at,
        risk_level="no_data",
        days_of_cover_estimate=0.0,
        lead_time_days_total=lead_time_days_total,
        recommendation=None,
        constraints_applied=ProductionOrderConstraintsApplied(),
        alternatives=[],
        explanation=explainability_mode_application.explanation,
    )
    return _SkipApplicationResult(response=response_application.response)
