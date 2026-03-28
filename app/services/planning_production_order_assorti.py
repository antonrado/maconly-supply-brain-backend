from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import BundleType

ASSORTI_CLASSIFICATION_SOURCE = "bundle_type.is_assorti"
ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE = "admin_defaults_assorti_mapping"
ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE = "global_default_assorti_mapping"
ASSORTI_CLASSIFICATION_MISSING_SOURCE = "bundle_type_missing_default_main"


def _parse_assorti_bundle_type_ids(raw_value: str | None) -> set[int]:
    if raw_value is None:
        return set()

    bundle_type_ids: set[int] = set()
    for token in raw_value.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            bundle_type_id = int(candidate)
        except ValueError:
            continue
        if bundle_type_id <= 0:
            continue
        bundle_type_ids.add(bundle_type_id)

    return bundle_type_ids


def _load_assorti_bundle_type_flags(
    db: Session,
    bundle_type_ids: list[int],
    admin_assorti_bundle_type_ids: set[int] | None = None,
    global_assorti_bundle_type_ids: set[int] | None = None,
) -> tuple[dict[int, bool], list[dict[str, int | bool | str]]]:
    if not bundle_type_ids:
        return {}, []

    unique_bundle_type_ids = sorted({int(bundle_type_id) for bundle_type_id in bundle_type_ids})

    bundle_types = (
        db.query(BundleType)
        .filter(BundleType.id.in_(unique_bundle_type_ids))
        .all()
    )
    bundle_type_by_id = {int(bundle_type.id): bundle_type for bundle_type in bundle_types}

    admin_assorti_ids = admin_assorti_bundle_type_ids or set()
    global_assorti_ids = global_assorti_bundle_type_ids or set()

    result: dict[int, bool] = {}
    traces: list[dict[str, int | bool | str]] = []

    for bundle_type_id in unique_bundle_type_ids:
        bundle_type = bundle_type_by_id.get(bundle_type_id)
        if bundle_type is not None and bool(bundle_type.is_assorti):
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_SOURCE
        elif bundle_type_id in admin_assorti_ids:
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE
        elif bundle_type_id in global_assorti_ids:
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE
        elif bundle_type is not None:
            is_assorti = False
            source = ASSORTI_CLASSIFICATION_SOURCE
        else:
            is_assorti = False
            source = ASSORTI_CLASSIFICATION_MISSING_SOURCE

        result[bundle_type_id] = is_assorti
        traces.append(
            {
                "bundle_type_id": int(bundle_type_id),
                "is_assorti": is_assorti,
                "source": source,
            }
        )

    return result, traces
