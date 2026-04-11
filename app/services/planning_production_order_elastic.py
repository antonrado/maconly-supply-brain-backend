from __future__ import annotations

from dataclasses import dataclass

from app.models.models import ElasticPlanningSettings, ProductionOrderElasticBinding, SkuUnit
from app.schemas.planning_production_order import ElasticConstraintApplied


def _resolve_elastic_binding_scope(
    bindings: list[ProductionOrderElasticBinding],
    line_qty: dict[tuple[int, int], int],
    sku_by_color_size: dict[tuple[int, int], SkuUnit],
) -> tuple[set[int], set[tuple[int, int]]]:
    active_line_keys = {
        key
        for key, qty in line_qty.items()
        if qty > 0
    }
    if not active_line_keys:
        return set(), set()

    active_color_ids = {color_id for color_id, _size_id in active_line_keys}
    active_line_keys_by_sku_id = {
        sku.id: key
        for key, sku in sku_by_color_size.items()
        if key in active_line_keys
    }

    applicable: set[int] = set()
    scoped_line_keys: set[tuple[int, int]] = set()
    for binding in bindings:
        if not binding.is_active:
            continue

        if binding.sku_unit_id is not None:
            line_key = active_line_keys_by_sku_id.get(binding.sku_unit_id)
            if line_key is not None:
                applicable.add(binding.elastic_type_id)
                scoped_line_keys.add(line_key)
                continue

        if binding.color_id is not None and binding.color_id in active_color_ids:
            applicable.add(binding.elastic_type_id)
            for line_key in active_line_keys:
                if line_key[0] == binding.color_id:
                    scoped_line_keys.add(line_key)

    return applicable, scoped_line_keys


@dataclass(frozen=True)
class _ElasticMinBatchUpliftResult:
    applicable_elastic_type_ids: set[int]
    elastic_scope_line_keys: set[tuple[int, int]]
    elastic_scope_mode: str
    scoped_elastic_row_count: int
    elastic_uplift_delta: int
    elastic_uplift_scope: str
    elastic_uplift_keys: list[tuple[int, int]]
    elastic_uplift_line_alloc: dict[tuple[int, int], int]
    constraint_applied: ElasticConstraintApplied | None


def _apply_elastic_min_batch_uplift(
    *,
    article_id: int,
    line_qty: dict[tuple[int, int], int],
    sku_by_color_size: dict[tuple[int, int], SkuUnit],
    elastic_rows: list[ElasticPlanningSettings],
    elastic_bindings: list[ProductionOrderElasticBinding],
    elastic_min_batch_default: int,
) -> _ElasticMinBatchUpliftResult:
    applicable_elastic_type_ids, elastic_scope_line_keys = _resolve_elastic_binding_scope(
        bindings=elastic_bindings,
        line_qty=line_qty,
        sku_by_color_size=sku_by_color_size,
    )

    scoped_elastic_rows = list(elastic_rows)
    elastic_scope_mode = "all_types"
    if elastic_bindings:
        elastic_scope_mode = "binding_scope"
        if applicable_elastic_type_ids:
            scoped_elastic_rows = [
                row for row in elastic_rows if row.elastic_type_id in applicable_elastic_type_ids
            ]
        else:
            scoped_elastic_rows = []

    current_total_units = sum(line_qty.values())

    elastic_target = elastic_min_batch_default
    elastic_type_id: int | None = None

    if elastic_bindings and not applicable_elastic_type_ids:
        elastic_target = 0

    for row in scoped_elastic_rows:
        candidate = row.elastic_min_batch_qty
        if candidate is None or candidate <= 0:
            candidate = elastic_min_batch_default

        if candidate > elastic_target:
            elastic_target = candidate
            elastic_type_id = row.elastic_type_id

    elastic_uplift_delta = 0
    elastic_uplift_scope = "none"
    elastic_uplift_keys: list[tuple[int, int]] = []
    elastic_uplift_line_alloc: dict[tuple[int, int], int] = {}
    constraint_applied: ElasticConstraintApplied | None = None

    if current_total_units > 0 and elastic_target > 0 and current_total_units < elastic_target:
        delta = elastic_target - current_total_units
        elastic_uplift_delta = delta
        constraint_applied = ElasticConstraintApplied(
            article_id=article_id,
            elastic_type_id=elastic_type_id,
            required=current_total_units,
            applied_min=elastic_target,
        )

        if line_qty:
            if elastic_bindings and elastic_scope_line_keys:
                keys = sorted(elastic_scope_line_keys)
                elastic_uplift_scope = "binding_scope"
            else:
                keys = sorted(line_qty.keys())
                elastic_uplift_scope = "all_lines"
            elastic_uplift_keys = list(keys)
            base_add = delta // len(keys)
            rem = delta % len(keys)
            for index, key in enumerate(keys):
                add_qty = base_add + (1 if index < rem else 0)
                line_qty[key] += add_qty
                if add_qty > 0:
                    elastic_uplift_line_alloc[key] = add_qty

    return _ElasticMinBatchUpliftResult(
        applicable_elastic_type_ids=applicable_elastic_type_ids,
        elastic_scope_line_keys=elastic_scope_line_keys,
        elastic_scope_mode=elastic_scope_mode,
        scoped_elastic_row_count=len(scoped_elastic_rows),
        elastic_uplift_delta=elastic_uplift_delta,
        elastic_uplift_scope=elastic_uplift_scope,
        elastic_uplift_keys=elastic_uplift_keys,
        elastic_uplift_line_alloc=elastic_uplift_line_alloc,
        constraint_applied=constraint_applied,
    )
