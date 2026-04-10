from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_explanation_warning_application import (
    _ExplanationWarningApplicationResult,
)


@dataclass(frozen=True)
class _ExplanationWarningUnpackApplicationResult:
    explanation_warnings: list[dict[str, object]]


def _apply_production_order_explanation_warning_unpack(
    *,
    explanation_warning_application: _ExplanationWarningApplicationResult,
) -> _ExplanationWarningUnpackApplicationResult:
    return _ExplanationWarningUnpackApplicationResult(
        explanation_warnings=explanation_warning_application.explanation_warnings,
    )
