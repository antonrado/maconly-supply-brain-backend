from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.models import (
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    ProductionOrderElasticBinding,
    SkuUnit,
)
from app.schemas.planning_production_order import ProductionOrderConstraintsApplied


@dataclass(frozen=True)
class _ConstraintApplicationResult:
    constraints_applied: ProductionOrderConstraintsApplied
    shared_color_pool: dict[str, object]
    applicable_elastic_type_ids: set[int]
    elastic_scope_line_keys: set[tuple[int, int]]
    elastic_scope_mode: str
    scoped_elastic_rows_count: int
    elastic_uplift_delta: int
    elastic_uplift_scope: str
    elastic_uplift_keys: list[tuple[int, int]]
    elastic_uplift_line_alloc: dict[tuple[int, int], int]


def _apply_production_order_constraints(
    *,
    db: Session,
    article_id: int,
    resource_allocation: object,
    all_recipe_color_ids: list[int],
    target_horizon_days: int,
    shared_color_pool_observation_window_days: int | None,
    shared_color_pool_as_of_date: date | None,
    fabric_min_batch_default: int,
    elastic_min_batch_default: int,
    line_qty: dict[tuple[int, int], int],
    color_to_sizes: dict[int, list[int]],
    size_weights: dict[int, float],
    sku_by_color_size: dict[tuple[int, int], SkuUnit],
    apply_shared_color_pool_fabric_min_batches: Callable[..., object],
    apply_elastic_min_batch_uplift: Callable[..., object],
) -> _ConstraintApplicationResult:
    colors = db.query(Color).filter(Color.id.in_(all_recipe_color_ids)).all()
    pantone_by_color: dict[int, str] = {}
    for color in colors:
        pantone_by_color[color.id] = color.pantone_code or f"COLOR-{color.id}"

    color_settings_rows = (
        db.query(ColorPlanningSettings)
        .filter(
            ColorPlanningSettings.article_id == article_id,
            ColorPlanningSettings.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )
    color_min_override = {
        row.color_id: row.fabric_min_batch_qty
        for row in color_settings_rows
        if row.fabric_min_batch_qty is not None and row.fabric_min_batch_qty > 0
    }

    constraints_applied = ProductionOrderConstraintsApplied(
        resource_allocation=resource_allocation
    )
    fabric_min_batch_constraints = apply_shared_color_pool_fabric_min_batches(
        db=db,
        article_id=article_id,
        pantone_by_color=pantone_by_color,
        target_horizon_days=target_horizon_days,
        observation_window_days=shared_color_pool_observation_window_days,
        as_of_date=shared_color_pool_as_of_date,
        all_recipe_color_ids=all_recipe_color_ids,
        fabric_min_batch_default=fabric_min_batch_default,
        color_min_override=color_min_override,
        line_qty=line_qty,
        color_to_sizes=color_to_sizes,
        global_size_weights=size_weights,
    )
    shared_color_pool = fabric_min_batch_constraints.shared_color_pool
    constraints_applied.fabric_min_batches.extend(
        fabric_min_batch_constraints.fabric_constraints
    )

    elastic_rows = (
        db.query(ElasticPlanningSettings)
        .filter(ElasticPlanningSettings.article_id == article_id)
        .all()
    )

    elastic_bindings = (
        db.query(ProductionOrderElasticBinding)
        .filter(
            ProductionOrderElasticBinding.article_id == article_id,
            ProductionOrderElasticBinding.is_active.is_(True),
        )
        .all()
    )

    elastic_uplift = apply_elastic_min_batch_uplift(
        article_id=article_id,
        line_qty=line_qty,
        sku_by_color_size=sku_by_color_size,
        elastic_rows=elastic_rows,
        elastic_bindings=elastic_bindings,
        elastic_min_batch_default=elastic_min_batch_default,
    )
    if elastic_uplift.constraint_applied is not None:
        constraints_applied.elastic_min_batches.append(
            elastic_uplift.constraint_applied
        )

    return _ConstraintApplicationResult(
        constraints_applied=constraints_applied,
        shared_color_pool=shared_color_pool,
        applicable_elastic_type_ids=elastic_uplift.applicable_elastic_type_ids,
        elastic_scope_line_keys=elastic_uplift.elastic_scope_line_keys,
        elastic_scope_mode=elastic_uplift.elastic_scope_mode,
        scoped_elastic_rows_count=elastic_uplift.scoped_elastic_row_count,
        elastic_uplift_delta=elastic_uplift.elastic_uplift_delta,
        elastic_uplift_scope=elastic_uplift.elastic_uplift_scope,
        elastic_uplift_keys=elastic_uplift.elastic_uplift_keys,
        elastic_uplift_line_alloc=elastic_uplift.elastic_uplift_line_alloc,
    )
