from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_candidate_lines_application import (
    _CandidateLinesApplicationResult,
)


@dataclass(frozen=True)
class _CandidateLinesUnpackApplicationResult:
    candidate_lines: list[object]


def _apply_production_order_candidate_lines_unpack(
    *,
    candidate_lines_application: _CandidateLinesApplicationResult,
) -> _CandidateLinesUnpackApplicationResult:
    return _CandidateLinesUnpackApplicationResult(
        candidate_lines=candidate_lines_application.candidate_lines,
    )
