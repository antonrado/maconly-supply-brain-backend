from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_constraint_application import (
    _ConstraintApplicationResult,
)


@dataclass(frozen=True)
class _ConstraintUnpackApplicationResult:
    constraints_applied: object
    shared_color_pool: dict[str, object]
    applicable_elastic_type_ids: set[int]
    elastic_scope_line_keys: set[tuple[int, int]]
    elastic_scope_mode: str
    scoped_elastic_rows_count: int
    elastic_uplift_delta: int
    elastic_uplift_scope: str
    elastic_uplift_keys: list[tuple[int, int]]
    elastic_uplift_line_alloc: dict[tuple[int, int], int]


def _apply_production_order_constraint_unpack(
    *,
    constraint_application: _ConstraintApplicationResult,
) -> _ConstraintUnpackApplicationResult:
    return _ConstraintUnpackApplicationResult(
        constraints_applied=constraint_application.constraints_applied,
        shared_color_pool=constraint_application.shared_color_pool,
        applicable_elastic_type_ids=constraint_application.applicable_elastic_type_ids,
        elastic_scope_line_keys=constraint_application.elastic_scope_line_keys,
        elastic_scope_mode=constraint_application.elastic_scope_mode,
        scoped_elastic_rows_count=constraint_application.scoped_elastic_rows_count,
        elastic_uplift_delta=constraint_application.elastic_uplift_delta,
        elastic_uplift_scope=constraint_application.elastic_uplift_scope,
        elastic_uplift_keys=constraint_application.elastic_uplift_keys,
        elastic_uplift_line_alloc=constraint_application.elastic_uplift_line_alloc,
    )
