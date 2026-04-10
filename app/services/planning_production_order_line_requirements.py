from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_math import (
    _allocate_units,
    _ceil_to_int,
    _normalize_weights,
)


@dataclass(frozen=True)
class _LineRequirementsPlan:
    color_probability: dict[int, float]
    line_required: dict[tuple[int, int], int]
    line_qty: dict[tuple[int, int], int]


def _build_line_requirements_plan(
    *,
    bundle_deficit_total: int,
    bundle_type_ids: list[int],
    all_recipe_color_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    shares_by_bundle: dict[int, float],
    color_to_sizes: dict[int, list[int]],
    size_weights: dict[int, float],
    stock_by_color_size: dict[tuple[int, int], int],
) -> _LineRequirementsPlan:
    color_probability: dict[int, float] = {
        color_id: 0.0 for color_id in all_recipe_color_ids
    }
    for color_id in all_recipe_color_ids:
        for bundle_type_id in bundle_type_ids:
            if color_id in recipe_colors_by_bundle[bundle_type_id]:
                color_probability[color_id] += shares_by_bundle.get(bundle_type_id, 0.0)

    if sum(color_probability.values()) <= 0:
        uniform = 1.0 / len(all_recipe_color_ids)
        color_probability = {color_id: uniform for color_id in all_recipe_color_ids}

    line_required: dict[tuple[int, int], int] = {}
    for color_id in all_recipe_color_ids:
        color_target_units = _ceil_to_int(
            bundle_deficit_total * color_probability.get(color_id, 0.0)
        )
        sizes_for_color = color_to_sizes.get(color_id, [])
        if not sizes_for_color:
            continue

        local_weights = _normalize_weights(
            sizes_for_color,
            {size_id: size_weights.get(size_id, 0.0) for size_id in sizes_for_color},
        )
        allocated = _allocate_units(color_target_units, local_weights)

        for size_id, qty in allocated.items():
            line_required[(color_id, size_id)] = qty

    line_qty: dict[tuple[int, int], int] = {}
    for key, required_qty in line_required.items():
        current_qty = stock_by_color_size.get(key, 0)
        line_qty[key] = max(required_qty - current_qty, 0)

    return _LineRequirementsPlan(
        color_probability=color_probability,
        line_required=line_required,
        line_qty=line_qty,
    )
