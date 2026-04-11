from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderRecommendationLine


@dataclass(frozen=True)
class _CandidateLinesApplicationResult:
    candidate_lines: list[ProductionOrderRecommendationLine]


def _apply_production_order_candidate_lines(
    *,
    article_id: int,
    line_qty: dict[tuple[int, int], int],
    layer3_decision_by_line: dict[tuple[int, int], str],
    build_candidate_lines: Callable[..., list[ProductionOrderRecommendationLine]],
) -> _CandidateLinesApplicationResult:
    candidate_lines = build_candidate_lines(
        article_id=article_id,
        line_qty=line_qty,
        layer3_decision_by_line=layer3_decision_by_line,
    )
    return _CandidateLinesApplicationResult(candidate_lines=candidate_lines)
