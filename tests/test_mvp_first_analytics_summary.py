from __future__ import annotations

import json

from scripts.mvp_first_analytics_summary import build_summary, write_summary


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_summary_extracts_first_analytics_signals(tmp_path):
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
    _write_json(
        tmp_path / "monitoring_risk_focus.json",
        {"items": [{"article_id": 1}, {"article_id": 2}]},
    )
    _write_json(
        tmp_path / "monitoring_timeseries.json",
        {"items": [{"metric": "risk_critical", "points": []}]},
    )

    summary = build_summary(report_dir=tmp_path)

    assert summary["production_order_direct"] == {
        "status": "ok",
        "article_id": 1,
        "risk_level": "critical",
        "days_of_cover_estimate": 10.0,
        "action": "order_minimum_only",
        "total_units": 100,
        "line_count": 2,
        "arrival_projection_status": "shortage_before_arrival",
        "projected_shortage_before_arrival": 25,
    }
    assert summary["production_order_from_wb"]["action"] == "wait"
    assert summary["shipment_comparison"]["categories"] == {"qty_mismatch": 1}
    assert summary["monitoring"]["overall_status"] == "warning"
    assert summary["monitoring"]["top_risk_count"] == 2
    assert summary["monitoring"]["timeseries_metrics"] == ["risk_critical"]


def test_write_summary_creates_summary_json(tmp_path):
    path = write_summary(report_dir=tmp_path)

    assert path == tmp_path / "summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["production_order_direct"]["status"] is None
    assert payload["shipment_comparison"]["categories"] == {}
