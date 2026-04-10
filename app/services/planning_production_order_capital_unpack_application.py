from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderRecommendationLine
from app.services.planning_production_order_capital_application import (
    _CapitalApplicationResult,
)


@dataclass(frozen=True)
class _CapitalUnpackApplicationResult:
    candidate_lines: list[ProductionOrderRecommendationLine]
    capital_rankings: list[dict[str, int | float | str]]
    capital_constraint_summary: dict[str, object]
    capital_constraint_contract: dict[str, str | dict[str, bool]]
    candidate_total_units: int


def _apply_production_order_capital_unpack(
    *,
    capital_application: _CapitalApplicationResult,
) -> _CapitalUnpackApplicationResult:
    return _CapitalUnpackApplicationResult(
        candidate_lines=capital_application.candidate_lines,
        capital_rankings=capital_application.capital_rankings,
        capital_constraint_summary=capital_application.capital_constraint_summary,
        capital_constraint_contract=capital_application.capital_constraint_contract,
        candidate_total_units=capital_application.candidate_total_units,
    )
