from __future__ import annotations

from app.services.planning_production_order_article import _build_article_not_found_detail
from app.services.planning_production_order_economics import (
    CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
)
from app.services.planning_production_order_freshness import (
    build_from_wb_freshness_blocker,
    build_from_wb_freshness_next_steps,
)
from app.services.wb_ingest import build_from_wb_readiness_next_steps

CAPITAL_GOVERNANCE_MODE_STRICT = "strict"
CAPITAL_GOVERNANCE_MODE_SAFE_DEFAULT = "safe_default"
CAPITAL_GOVERNANCE_WARNING_CODE_SAFE_DEFAULT = "available_capital_safe_default_applied"
CAPITAL_GOVERNANCE_STATUS_SAFE_DEFAULT_APPLIED = "safe_default_zero_capital_applied"
CAPITAL_GOVERNANCE_SOURCE_SAFE_DEFAULT = "safe_default_zero_capital"


def _build_from_wb_freshness_failure_detail(
    *,
    article_id: int,
    freshness_status: str,
    freshness_mode: str,
    sales_age_days: int | None,
    stock_oldest_age_days: int | None,
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    threshold_source: dict[str, str],
) -> dict[str, object]:
    stale_sales = sales_age_days is not None and sales_age_days > sales_stale_after_days
    stale_stock = stock_oldest_age_days is not None and stock_oldest_age_days > stock_stale_after_days

    next_steps = build_from_wb_freshness_next_steps(
        freshness_status=freshness_status,
        sales_age_days=sales_age_days,
        stock_oldest_age_days=stock_oldest_age_days,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
    )
    blocker = build_from_wb_freshness_blocker(
        freshness_status=freshness_status,
        sales_age_days=sales_age_days,
        stock_oldest_age_days=stock_oldest_age_days,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
    )

    stale_components: list[str] = []
    if stale_sales:
        stale_components.append("sales")
    if stale_stock:
        stale_components.append("stock")

    return {
        "code": "wb_data_freshness_failed",
        "message": "WB data freshness check failed",
        "article_id": int(article_id),
        "field": "freshness_mode",
        "field_metadata": {
            "description": "from-WB freshness gate mode",
            "type": "Literal['warn', 'strict']",
        },
        "freshness_mode": freshness_mode,
        "freshness_status": freshness_status,
        "sales_age_days": sales_age_days,
        "stock_oldest_age_days": stock_oldest_age_days,
        "threshold_days": {
            "sales": int(sales_stale_after_days),
            "stock": int(stock_stale_after_days),
        },
        "threshold_source": dict(threshold_source),
        "readiness_endpoint": "/api/v1/wb/from-wb/readiness",
        "blocker": blocker,
        "stale_components": stale_components,
        "next_steps": next_steps,
    }


def _build_from_wb_no_mapping_detail(
    *,
    article_id: int,
    requested_bundle_type_ids: list[int] | None,
    blocker: str = "no_wb_mapping",
) -> dict[str, object]:
    return {
        "code": "no_wb_mapped_bundle_types",
        "message": "No WB-mapped bundle types found for the article",
        "article_id": int(article_id),
        "field": "bundle_type_ids",
        "field_metadata": {
            "description": "List of bundle type IDs",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [int(bundle_type_id) for bundle_type_id in (requested_bundle_type_ids or [])],
        "readiness_endpoint": "/api/v1/wb/from-wb/readiness",
        "blocker": blocker,
        "next_steps": build_from_wb_readiness_next_steps(blocker),
    }


def _build_from_wb_missing_requested_bundle_type_detail(
    *,
    article_id: int,
    missing_bundle_type_ids: list[int],
    requested_bundle_type_ids: list[int],
) -> dict[str, object]:
    return {
        "code": "missing_wb_mapping_for_requested_bundle_types",
        "message": "Missing WB mapping for requested bundle_type_id(s)",
        "article_id": int(article_id),
        "field": "bundle_type_ids",
        "field_metadata": {
            "description": "List of bundle type IDs",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [int(bundle_type_id) for bundle_type_id in requested_bundle_type_ids],
        "missing_bundle_type_ids": [int(bundle_type_id) for bundle_type_id in missing_bundle_type_ids],
        "readiness_endpoint": "/api/v1/wb/from-wb/readiness",
        "blocker": "missing_wb_mapping_for_requested_bundle_types",
        "next_steps": build_from_wb_readiness_next_steps("missing_wb_mapping_for_requested_bundle_types"),
    }


def _build_direct_missing_bundle_recipe_detail(
    *,
    article_id: int,
    requested_bundle_type_ids: list[int],
    missing_bundle_type_ids: list[int],
) -> dict[str, object]:
    all_missing = sorted(int(bundle_type_id) for bundle_type_id in missing_bundle_type_ids)
    requested = sorted(int(bundle_type_id) for bundle_type_id in requested_bundle_type_ids)
    code = "no_bundle_recipe" if all_missing == requested else "missing_bundle_recipe_bundle_types"
    message = (
        "No bundle recipe defined for the requested bundle types"
        if code == "no_bundle_recipe"
        else "Bundle recipe is missing for some requested bundle types"
    )
    next_steps = (
        ["create_bundle_recipe_for_requested_bundle_type_ids"]
        if code == "no_bundle_recipe"
        else ["add_bundle_recipe_for_missing_bundle_type_ids"]
    )
    return {
        "code": code,
        "message": message,
        "article_id": int(article_id),
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": requested,
        "missing_bundle_type_ids": all_missing,
        "blocker": code,
        "next_steps": next_steps,
    }


def _build_direct_missing_sku_scope_detail(
    *,
    article_id: int,
    requested_bundle_type_ids: list[int],
    recipe_color_ids: list[int],
) -> dict[str, object]:
    return {
        "code": "no_sku_units_for_recipe_colors",
        "message": "No SKU units found for article and recipe colors",
        "article_id": int(article_id),
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [int(bundle_type_id) for bundle_type_id in requested_bundle_type_ids],
        "recipe_color_ids": [int(color_id) for color_id in recipe_color_ids],
        "blocker": "no_sku_units_for_recipe_colors",
        "next_steps": build_from_wb_readiness_next_steps("no_sku_units_for_recipe_colors"),
    }


def _build_missing_available_capital_strict_detail(
    *,
    article_id: int,
    economics_trust_level: object,
) -> dict[str, object]:
    return {
        "code": "missing_available_capital_strict",
        "message": "available_capital is required for production-order proposal in strict capital governance mode",
        "article_id": int(article_id),
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for strict capital governance mode",
            "type": "number",
        },
        "capital_constraint_status": CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
        "severity": "HIGH",
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": economics_trust_level,
        "next_steps": ["provide_available_capital_override_or_default"],
    }


def _build_admin_settings_field_metadata(*, field: str) -> dict[str, str]:
    if field == "size_weights.size_id":
        return {
            "description": "Size identifiers from size_weights input",
            "type": "list[int]",
        }
    if field == "elastic_bindings.elastic_type_id":
        return {
            "description": "Elastic type identifiers from elastic_bindings input",
            "type": "list[int]",
        }
    if field == "elastic_bindings.color_id":
        return {
            "description": "Color identifier from elastic_bindings input",
            "type": "int",
        }
    if field == "elastic_bindings.sku_unit_id":
        return {
            "description": "SKU unit identifier from elastic_bindings input",
            "type": "int",
        }
    if field == "assorti_bundle_type_ids":
        return {
            "description": "Assorti bundle type identifiers",
            "type": "list[int]",
        }
    if field == "in_flight_supply_defaults":
        return {
            "description": "In-flight supply default entries from request input",
            "type": "list[object]",
        }
    return {
        "description": "Production-order admin settings input field",
        "type": "unknown",
    }


def _build_admin_settings_validation_detail(
    *,
    code: str,
    message: str,
    article_id: int,
    field: str,
    next_steps: list[str],
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    detail = {
        "code": code,
        "message": message,
        "article_id": int(article_id),
        "field": field,
        "field_metadata": _build_admin_settings_field_metadata(field=field),
        "next_steps": list(next_steps),
    }
    if extra:
        detail.update(extra)
    return detail


def _build_available_capital_safe_default_warning(
    *,
    article_id: int,
    economics_trust_level: object,
) -> dict[str, object]:
    return {
        "code": CAPITAL_GOVERNANCE_WARNING_CODE_SAFE_DEFAULT,
        "severity": "HIGH",
        "message": (
            "available_capital missing; safe_default mode applied zero-capital fallback to avoid "
            "unconstrained recommendations"
        ),
        "article_id": int(article_id),
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for safe_default capital governance mode",
            "type": "number",
        },
        "capital_governance_status": CAPITAL_GOVERNANCE_STATUS_SAFE_DEFAULT_APPLIED,
        "capital_governance_mode": CAPITAL_GOVERNANCE_MODE_SAFE_DEFAULT,
        "available_capital_effective": 0.0,
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": economics_trust_level,
        "next_steps": ["provide_available_capital_override_or_default"],
    }


def _build_layer_proxy_invalid_values_ignored_warning(
    *,
    article_id: int,
    invalid_values_ignored: list[dict[str, object]],
) -> dict[str, object]:
    ignored_fields = sorted(
        {
            str(item.get("field", "")).strip()
            for item in invalid_values_ignored
            if str(item.get("field", "")).strip()
        }
    )
    ignored_sources = sorted(
        {
            str(item.get("invalid_source", "")).strip()
            for item in invalid_values_ignored
            if str(item.get("invalid_source", "")).strip()
        }
    )
    return {
        "code": "layer_proxy_invalid_values_ignored_at_runtime",
        "severity": "MEDIUM",
        "message": (
            "one or more production-order layer proxy values were invalid and ignored at runtime; "
            "lower-precedence or default values were used instead"
        ),
        "article_id": int(article_id),
        "field": "layer_proxy_settings",
        "field_metadata": {
            "description": "Production-order Layer 3/5 proxy settings resolved from request/admin/global sources",
            "type": "object",
        },
        "ignored_value_count": len(invalid_values_ignored),
        "ignored_fields": ignored_fields,
        "ignored_sources": ignored_sources,
        "ignored_values": invalid_values_ignored,
        "action": "Review stored production-order layer proxy values; each unit-interval setting must stay within [0, 1].",
        "next_steps": ["repair_layer_proxy_settings_values"],
    }


def _build_shortage_wait_blocked_by_capital_constraint_warning(
    *,
    article_id: int,
    projected_shortage_before_arrival: int,
    capital_constraint_summary: dict[str, object],
    available_capital_effective: float | None,
) -> dict[str, object]:
    return {
        "code": "shortage_before_arrival_wait_blocked_by_capital_constraint",
        "severity": "HIGH",
        "message": (
            "shortage_before_arrival detected, but recommendation remained wait because capital "
            "constraint trimmed feasible order quantity to zero"
        ),
        "article_id": int(article_id),
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input applied to production-order capital constraint",
            "type": "number",
        },
        "arrival_projection_status": "shortage_before_arrival",
        "projected_shortage_before_arrival": int(projected_shortage_before_arrival),
        "recommendation_action": "wait",
        "capital_constraint_status": capital_constraint_summary.get("status"),
        "available_capital_effective": available_capital_effective,
        "required_capital_before_constraint": capital_constraint_summary.get(
            "required_capital_before_constraint"
        ),
        "allocated_capital_after_constraint": capital_constraint_summary.get(
            "allocated_capital_after_constraint"
        ),
        "action": "Provide or increase available_capital before treating wait as safe under shortage.",
        "next_steps": ["provide_available_capital_override_or_default"],
    }
