from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import (
    ProductionOrderAlternative,
    ProductionOrderArrivalProjection,
    ProductionOrderPhysicalScope,
    ProductionOrderRecommendation,
)
from app.services.planning_production_order_scope_recommendation import (
    _ScopeRecommendationResult,
)


@dataclass(frozen=True)
class _ScopeRecommendationUnpackApplicationResult:
    physical_scope: ProductionOrderPhysicalScope
    arrival_projection: ProductionOrderArrivalProjection
    action: str
    recommendation: ProductionOrderRecommendation
    alternatives: list[ProductionOrderAlternative]


def _apply_production_order_scope_recommendation_unpack(
    *,
    scope_recommendation: _ScopeRecommendationResult,
) -> _ScopeRecommendationUnpackApplicationResult:
    return _ScopeRecommendationUnpackApplicationResult(
        physical_scope=scope_recommendation.physical_scope,
        arrival_projection=scope_recommendation.arrival_projection,
        action=scope_recommendation.action,
        recommendation=scope_recommendation.recommendation,
        alternatives=scope_recommendation.alternatives,
    )
