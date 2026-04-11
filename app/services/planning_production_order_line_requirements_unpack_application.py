from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_line_requirements_application import (
    _LineRequirementsApplicationResult,
)


@dataclass(frozen=True)
class _LineRequirementsUnpackApplicationResult:
    color_probability: dict[int, float]
    line_required: dict[tuple[int, int], int]
    line_qty: dict[tuple[int, int], int]


def _apply_production_order_line_requirements_unpack(
    *,
    line_requirements_application: _LineRequirementsApplicationResult,
) -> _LineRequirementsUnpackApplicationResult:
    return _LineRequirementsUnpackApplicationResult(
        color_probability=line_requirements_application.color_probability,
        line_required=line_requirements_application.line_required,
        line_qty=line_requirements_application.line_qty,
    )
