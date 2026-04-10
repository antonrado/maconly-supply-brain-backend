from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.schemas.planning_production_order import ProductionOrderProposalResponse


@dataclass(frozen=True)
class _ResponseApplicationResult:
    response: ProductionOrderProposalResponse


def _apply_production_order_response(
    *,
    status: str,
    article_id: int,
    generated_at: datetime,
    risk_level: str,
    days_of_cover_estimate: float,
    lead_time_days_total: int,
    recommendation: object | None,
    constraints_applied: object,
    alternatives: list[object],
    explanation: object,
    physical_scope: object | None = None,
    arrival_projection: object | None = None,
) -> _ResponseApplicationResult:
    response = ProductionOrderProposalResponse(
        status=status,
        article_id=article_id,
        generated_at=generated_at,
        risk_level=risk_level,
        days_of_cover_estimate=days_of_cover_estimate,
        lead_time_days_total=lead_time_days_total,
        recommendation=recommendation,
        constraints_applied=constraints_applied,
        physical_scope=physical_scope,
        arrival_projection=arrival_projection,
        alternatives=alternatives,
        explanation=explanation,
    )
    return _ResponseApplicationResult(response=response)
