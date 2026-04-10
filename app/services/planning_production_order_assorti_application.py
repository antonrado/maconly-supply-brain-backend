from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class _AssortiApplicationResult:
    admin_assorti_bundle_type_ids: set[int]
    global_assorti_bundle_type_ids: set[int]
    assorti_by_bundle_type: dict[int, bool]
    assorti_classification_by_bundle_type: list[dict[str, int | bool | str]]
    assorti_bundle_type_count: int
    main_bundle_type_count: int
    assorti_classification_source_breakdown: dict[str, int]


def _apply_production_order_assorti_classification(
    *,
    db: Session,
    article_settings: object | None,
    global_settings: object | None,
    bundle_type_ids: list[int],
    parse_assorti_bundle_type_ids: Callable[[str | None], set[int]],
    load_assorti_bundle_type_flags: Callable[
        ..., tuple[dict[int, bool], list[dict[str, int | bool | str]]]
    ],
) -> _AssortiApplicationResult:
    admin_assorti_bundle_type_ids = parse_assorti_bundle_type_ids(
        getattr(article_settings, "production_order_assorti_bundle_type_ids", None)
        if article_settings is not None
        else None
    )
    global_assorti_bundle_type_ids = parse_assorti_bundle_type_ids(
        getattr(global_settings, "default_production_order_assorti_bundle_type_ids", None)
        if global_settings is not None
        else None
    )

    assorti_by_bundle_type, assorti_classification_by_bundle_type = (
        load_assorti_bundle_type_flags(
            db=db,
            bundle_type_ids=bundle_type_ids,
            admin_assorti_bundle_type_ids=admin_assorti_bundle_type_ids,
            global_assorti_bundle_type_ids=global_assorti_bundle_type_ids,
        )
    )
    assorti_bundle_type_count = sum(
        1
        for item in assorti_classification_by_bundle_type
        if bool(item.get("is_assorti"))
    )
    main_bundle_type_count = max(
        len(assorti_classification_by_bundle_type) - assorti_bundle_type_count,
        0,
    )
    assorti_classification_source_counts: dict[str, int] = {}
    for item in assorti_classification_by_bundle_type:
        source = str(item.get("source", "unknown"))
        assorti_classification_source_counts[source] = (
            assorti_classification_source_counts.get(source, 0) + 1
        )
    assorti_classification_source_breakdown = {
        source: assorti_classification_source_counts[source]
        for source in sorted(assorti_classification_source_counts)
    }
    return _AssortiApplicationResult(
        admin_assorti_bundle_type_ids=admin_assorti_bundle_type_ids,
        global_assorti_bundle_type_ids=global_assorti_bundle_type_ids,
        assorti_by_bundle_type=assorti_by_bundle_type,
        assorti_classification_by_bundle_type=assorti_classification_by_bundle_type,
        assorti_bundle_type_count=assorti_bundle_type_count,
        main_bundle_type_count=main_bundle_type_count,
        assorti_classification_source_breakdown=assorti_classification_source_breakdown,
    )
