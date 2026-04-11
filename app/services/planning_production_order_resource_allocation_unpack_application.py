from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderResourceAllocationApplied
from app.services.planning_production_order_resource_allocation_application import (
    _ResourceAllocationApplicationResult,
)


@dataclass(frozen=True)
class _ResourceAllocationUnpackApplicationResult:
    resource_allocation: ProductionOrderResourceAllocationApplied
    competition_raw_by_bundle: dict[int, int]
    competition_raw_bundle_stock: int
    competition_raw_breakdown: str
    available_bundles_for_cover: int


def _apply_production_order_resource_allocation_unpack(
    *,
    resource_allocation_application: _ResourceAllocationApplicationResult,
) -> _ResourceAllocationUnpackApplicationResult:
    return _ResourceAllocationUnpackApplicationResult(
        resource_allocation=resource_allocation_application.resource_allocation,
        competition_raw_by_bundle=resource_allocation_application.competition_raw_by_bundle,
        competition_raw_bundle_stock=resource_allocation_application.competition_raw_bundle_stock,
        competition_raw_breakdown=resource_allocation_application.competition_raw_breakdown,
        available_bundles_for_cover=resource_allocation_application.available_bundles_for_cover,
    )
