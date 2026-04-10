from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer2_allocation_application import (
    _Layer2AllocationApplicationResult,
)


@dataclass(frozen=True)
class _Layer2AllocationUnpackApplicationResult:
    layer2_allocation_decisions: list[dict[str, int | float | str]]
    layer2_allocation_summary: dict[str, int]


def _apply_production_order_layer2_allocation_unpack(
    *,
    layer2_allocation_application: _Layer2AllocationApplicationResult,
) -> _Layer2AllocationUnpackApplicationResult:
    return _Layer2AllocationUnpackApplicationResult(
        layer2_allocation_decisions=layer2_allocation_application.layer2_allocation_decisions,
        layer2_allocation_summary=layer2_allocation_application.layer2_allocation_summary,
    )
