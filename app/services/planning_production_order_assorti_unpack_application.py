from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_assorti_application import (
    _AssortiApplicationResult,
)


@dataclass(frozen=True)
class _AssortiUnpackApplicationResult:
    admin_assorti_bundle_type_ids: set[int]
    global_assorti_bundle_type_ids: set[int]
    assorti_by_bundle_type: dict[int, bool]
    assorti_classification_by_bundle_type: list[dict[str, int | bool | str]]
    assorti_bundle_type_count: int
    main_bundle_type_count: int
    assorti_classification_source_breakdown: dict[str, int]


def _apply_production_order_assorti_unpack(
    *,
    assorti_application: _AssortiApplicationResult,
) -> _AssortiUnpackApplicationResult:
    return _AssortiUnpackApplicationResult(
        admin_assorti_bundle_type_ids=assorti_application.admin_assorti_bundle_type_ids,
        global_assorti_bundle_type_ids=assorti_application.global_assorti_bundle_type_ids,
        assorti_by_bundle_type=assorti_application.assorti_by_bundle_type,
        assorti_classification_by_bundle_type=assorti_application.assorti_classification_by_bundle_type,
        assorti_bundle_type_count=assorti_application.assorti_bundle_type_count,
        main_bundle_type_count=assorti_application.main_bundle_type_count,
        assorti_classification_source_breakdown=assorti_application.assorti_classification_source_breakdown,
    )
