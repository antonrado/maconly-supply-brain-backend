from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderResourceAllocationApplied


@dataclass(frozen=True)
class _ResourceAllocationApplicationResult:
    resource_allocation: ProductionOrderResourceAllocationApplied
    competition_raw_by_bundle: dict[int, int]
    competition_raw_bundle_stock: int
    competition_raw_breakdown: str
    available_bundles_for_cover: int


def _apply_production_order_resource_allocation(
    *,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    stock_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
    ready_bundle_stock_total: int,
    build_competition_aware_resource_allocation: Callable[
        ..., ProductionOrderResourceAllocationApplied
    ],
) -> _ResourceAllocationApplicationResult:
    resource_allocation = build_competition_aware_resource_allocation(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        stock_by_color_size=stock_by_color_size,
        shares_by_bundle=shares_by_bundle,
    )
    competition_raw_by_bundle = {
        int(bundle_type_id): int(reserved_qty)
        for bundle_type_id, reserved_qty in resource_allocation.reserved_bundle_units.items()
    }
    competition_raw_bundle_stock = sum(competition_raw_by_bundle.values())
    competition_raw_breakdown = ", ".join(
        f"{bundle_type_id}:{competition_raw_by_bundle.get(bundle_type_id, 0)}"
        for bundle_type_id in bundle_type_ids
    )
    available_bundles_for_cover = ready_bundle_stock_total + competition_raw_bundle_stock
    return _ResourceAllocationApplicationResult(
        resource_allocation=resource_allocation,
        competition_raw_by_bundle=competition_raw_by_bundle,
        competition_raw_bundle_stock=competition_raw_bundle_stock,
        competition_raw_breakdown=competition_raw_breakdown,
        available_bundles_for_cover=available_bundles_for_cover,
    )
