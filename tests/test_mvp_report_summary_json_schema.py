from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from scripts.mvp_first_analytics_summary import build_summary as build_first_analytics_summary
from scripts.mvp_live_readiness_summary import build_summary as build_live_readiness_summary


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "reporting"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise AssertionError(f"Unsupported schema type: {expected_type}")


def _matches_format(value: Any, expected_format: str) -> bool:
    if value is None:
        return True
    if expected_format == "date-time":
        if not isinstance(value, str):
            return False
        try:
            dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    if expected_format == "date":
        if not isinstance(value, str):
            return False
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    raise AssertionError(f"Unsupported schema format: {expected_format}")


def _assert_valid_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "const" in schema:
        assert value == schema["const"], f"{path}: expected const {schema['const']!r}, got {value!r}"

    if "enum" in schema:
        assert value in schema["enum"], f"{path}: expected one of {schema['enum']!r}, got {value!r}"

    expected_type = schema.get("type")
    if expected_type is not None:
        allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
        assert any(_matches_type(value, item) for item in allowed_types), (
            f"{path}: expected type {allowed_types!r}, got {type(value).__name__}"
        )

    expected_format = schema.get("format")
    if expected_format is not None:
        assert _matches_format(value, expected_format), (
            f"{path}: expected format {expected_format!r}, got {value!r}"
        )

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            assert key in value, f"{path}: missing required key {key!r}"

        properties = schema.get("properties") or {}
        additional_properties = schema.get("additionalProperties", True)

        for key, item in value.items():
            if key in properties:
                _assert_valid_schema(item, properties[key], f"{path}.{key}")
                continue
            if additional_properties is False:
                raise AssertionError(f"{path}: unexpected key {key!r}")
            if isinstance(additional_properties, dict):
                _assert_valid_schema(item, additional_properties, f"{path}.{key}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _assert_valid_schema(item, item_schema, f"{path}[{index}]")


def test_mvp_first_analytics_summary_matches_json_schema(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "requests.json",
        {
            "generated_at": "2030-01-01T00:00:00+00:00",
            "base_url": "http://127.0.0.1:8010",
            "requests": [
                {"name": "planning-core-health", "method": "GET", "url": "http://127.0.0.1:8010/health", "body": None},
                {
                    "name": "production-order-direct",
                    "method": "POST",
                    "url": "http://127.0.0.1:8010/proposal",
                    "body": {"article_id": 1},
                },
            ],
        },
    )
    _write_json(
        tmp_path / "production_order_direct.json",
        {
            "status": "ok",
            "article_id": 1,
            "risk_level": "critical",
            "days_of_cover_estimate": 10.0,
            "recommendation": {"action": "order_minimum_only", "total_units": 100, "lines": [{}, {}]},
            "arrival_projection": {
                "status": "shortage_before_arrival",
                "projected_shortage_before_arrival": 25,
            },
        },
    )
    _write_json(
        tmp_path / "production_order_from_wb.json",
        {
            "status": "ok",
            "article_id": 1,
            "risk_level": "warning",
            "days_of_cover_estimate": 12.5,
            "recommendation": {"action": "wait", "total_units": 0, "lines": []},
            "arrival_projection": {"status": "safe_cover_until_arrival"},
        },
    )
    _write_json(
        tmp_path / "shipment_comparison.json",
        {
            "target_date": "2030-01-31",
            "wb_arrival_date": "2030-01-31",
            "divergence_summary": {
                "has_divergence": True,
                "article_count": 2,
                "divergent_article_count": 1,
                "categories": {"qty_mismatch": 1},
            },
            "scope_normalization": {
                "normalization_strategy": "requested_article_ids",
                "canonical_planning_horizon_days": 90,
            },
        },
    )
    _write_json(
        tmp_path / "monitoring_dashboard.json",
        {
            "status": {"overall_status": "warning", "critical_alerts": 1, "warning_alerts": 2},
            "snapshot": {
                "risks": {"critical": 1, "warning": 2},
                "orders": {"articles_with_orders": 3, "total_final_order_qty": 400},
            },
        },
    )
    _write_json(tmp_path / "monitoring_risk_focus.json", {"items": [{"article_id": 1}, {"article_id": 2}]})
    _write_json(tmp_path / "monitoring_timeseries.json", {"items": [{"metric": "risk_critical", "points": []}]})

    summary = build_first_analytics_summary(report_dir=tmp_path)
    schema = _load_schema("mvp_first_analytics_summary.schema.json")

    _assert_valid_schema(summary, schema)


def test_mvp_live_readiness_summary_matches_json_schema() -> None:
    payload = {
        "total_articles_considered": 3,
        "ready_articles": 1,
        "not_ready_articles": 2,
        "items": [
            {
                "article_id": 1,
                "article_code": "READY",
                "ready_for_from_wb": True,
                "blocker": None,
                "freshness_status": "fresh",
                "next_steps": [],
            },
            {
                "article_id": 2,
                "article_code": "NO-SALES",
                "ready_for_from_wb": False,
                "blocker": "no_wb_sales_data",
                "freshness_status": "missing_sales_data",
                "next_steps": ["run_wb_sales_daily_sync_live"],
            },
            {
                "article_id": 3,
                "article_code": "NO-STOCK",
                "ready_for_from_wb": False,
                "blocker": "no_wb_stock_data",
                "freshness_status": "missing_stock_data",
                "next_steps": ["run_wb_stock_sync_live"],
            },
        ],
    }
    request = {
        "article_id": 2,
        "limit": 20,
        "freshness_sales_stale_after_days": 3,
        "freshness_stock_stale_after_days": 4,
    }

    summary = build_live_readiness_summary(payload, request_payload=request)
    schema = _load_schema("mvp_live_readiness_summary.schema.json")

    _assert_valid_schema(summary, schema)
