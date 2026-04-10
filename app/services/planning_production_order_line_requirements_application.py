from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.planning_production_order_line_requirements import _LineRequirementsPlan


@dataclass(frozen=True)
class _LineRequirementsApplicationResult:
    color_probability: dict[int, float]
    line_required: dict[tuple[int, int], int]
    line_qty: dict[tuple[int, int], int]


def _apply_production_order_line_requirements(
    *,
    bundle_deficit_total: int,
    bundle_type_ids: list[int],
    all_recipe_color_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    shares_by_bundle: dict[int, float],
    color_to_sizes: dict[int, list[int]],
    size_weights: dict[int, float],
    stock_by_color_size: dict[tuple[int, int], int],
    build_line_requirements_plan: Callable[..., _LineRequirementsPlan],
) -> _LineRequirementsApplicationResult:
    line_requirements_plan = build_line_requirements_plan(
        bundle_deficit_total=bundle_deficit_total,
        bundle_type_ids=bundle_type_ids,
        all_recipe_color_ids=all_recipe_color_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        shares_by_bundle=shares_by_bundle,
        color_to_sizes=color_to_sizes,
        size_weights=size_weights,
        stock_by_color_size=stock_by_color_size,
    )
    return _LineRequirementsApplicationResult(
        color_probability=line_requirements_plan.color_probability,
        line_required=line_requirements_plan.line_required,
        line_qty=line_requirements_plan.line_qty,
    )
