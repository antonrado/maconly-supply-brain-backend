from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.json_schema_subset import assert_valid_schema
from scripts.mvp_first_analytics_summary import build_summary as build_first_analytics_summary
from scripts.mvp_live_readiness_summary import build_summary as build_live_readiness_summary


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "reporting"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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

    summary = build_first_analytics_summary(tmp_path)
    schema = _load_schema("mvp_first_analytics_summary.schema.json")

    assert_valid_schema(summary, schema)


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

    assert_valid_schema(summary, schema)


def test_mvp_first_analytics_summary_schema_rejects_unexpected_top_level_key(tmp_path: Path) -> None:
    _write_json(tmp_path / "requests.json", {"generated_at": "2030-01-01T00:00:00+00:00", "base_url": "http://127.0.0.1:8010", "requests": []})
    _write_json(
        tmp_path / "production_order_direct.json",
        {
            "status": "ok",
            "article_id": 1,
            "risk_level": "critical",
            "days_of_cover_estimate": 10.0,
            "recommendation": {"action": "order_minimum_only", "total_units": 100, "lines": [{}, {}]},
            "arrival_projection": {"status": "shortage_before_arrival", "projected_shortage_before_arrival": 25},
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
            "scope_normalization": {"normalization_strategy": "requested_article_ids", "canonical_planning_horizon_days": 90},
        },
    )
    _write_json(
        tmp_path / "monitoring_dashboard.json",
        {
            "status": {"overall_status": "warning", "critical_alerts": 1, "warning_alerts": 2},
            "snapshot": {"risks": {"critical": 1, "warning": 2}, "orders": {"articles_with_orders": 3, "total_final_order_qty": 400}},
        },
    )
    _write_json(tmp_path / "monitoring_risk_focus.json", {"items": [{"article_id": 1}]})
    _write_json(tmp_path / "monitoring_timeseries.json", {"items": [{"metric": "risk_critical", "points": []}]})

    summary = build_first_analytics_summary(tmp_path)
    summary["unexpected"] = True
    schema = _load_schema("mvp_first_analytics_summary.schema.json")

    try:
        assert_valid_schema(summary, schema)
    except ValueError as exc:
        assert "unexpected key 'unexpected'" in str(exc)
    else:
        raise AssertionError("expected first analytics summary schema to reject an unexpected top-level key")
