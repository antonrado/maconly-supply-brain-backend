from __future__ import annotations

import json

from scripts.mvp_first_analytics_summary import build_summary, render_markdown_summary, write_summary


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_summary_extracts_first_analytics_signals(tmp_path):
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
    _write_json(
        tmp_path / "monitoring_risk_focus.json",
        {"items": [{"article_id": 1}, {"article_id": 2}]},
    )
    _write_json(
        tmp_path / "monitoring_timeseries.json",
        {"items": [{"metric": "risk_critical", "points": []}]},
    )

    summary = build_summary(report_dir=tmp_path)

    assert summary["report_type"] == "mvp_first_analytics"
    assert summary["summary_schema_version"] == "1.0"
    assert summary["artifact_status"] == "incomplete"
    assert "seed_payloads.json" in summary["missing_input_files"]
    assert summary["validation_messages"] == [
        "MVP first analytics report is incomplete; restore missing input files: seed_payloads.json, planning_core_health.json."
    ]
    input_files = {item["name"]: item for item in summary["input_files"]}
    assert input_files["requests"] == {"name": "requests", "filename": "requests.json", "present": True}
    assert input_files["seed_payloads"] == {"name": "seed_payloads", "filename": "seed_payloads.json", "present": False}
    assert input_files["production_order_direct"]["present"] is True
    assert summary["request_metadata"] == {
        "generated_at": "2030-01-01T00:00:00+00:00",
        "base_url": "http://127.0.0.1:8010",
        "request_count": 2,
        "requests": [
            {
                "name": "planning-core-health",
                "method": "GET",
                "url": "http://127.0.0.1:8010/health",
                "has_body": False,
            },
            {
                "name": "production-order-direct",
                "method": "POST",
                "url": "http://127.0.0.1:8010/proposal",
                "has_body": True,
            },
        ],
    }
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
    assert len(summary["next_actions"]) == 4
    assert summary["next_actions"][0].startswith("Review production-order recommendations")
    assert "shortage-before-arrival" in summary["next_actions"][1]
    assert "qty_mismatch=1" in summary["next_actions"][2]
    assert "overall=warning" in summary["next_actions"][3]

    markdown = render_markdown_summary(summary)
    assert "# MVP First Analytics Summary" in markdown
    assert "- **Report type**: `mvp_first_analytics`" in markdown
    assert "- **Summary schema version**: `1.0`" in markdown
    assert "- **Artifact status**: `incomplete`" in markdown
    assert "## Validation" in markdown
    assert "- **Validation**: MVP first analytics report is incomplete" in markdown
    assert "seed_payloads.json" in markdown
    assert "## Input files" in markdown
    assert "| requests | `requests.json` | true |" in markdown
    assert "- **Request count**: `2`" in markdown
    assert "| production-order-direct | POST | true |" in markdown
    assert "## Next actions" in markdown
    assert "- **Action**: Review production-order recommendations" in markdown
    assert "| Direct | ok | 1 | critical | order_minimum_only | 100 | 2 | shortage_before_arrival | 25 |" in markdown
    assert "- **Categories**: `qty_mismatch=1`" in markdown
    assert "- **Overall status**: `warning`" in markdown


def test_write_summary_creates_summary_json(tmp_path):
    path = write_summary(report_dir=tmp_path)

    assert path == tmp_path / "summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "mvp_first_analytics"
    assert payload["summary_schema_version"] == "1.0"
    assert payload["artifact_status"] == "incomplete"
    assert "seed_payloads.json" in payload["missing_input_files"]
    assert payload["validation_messages"][0].startswith("MVP first analytics report is incomplete")
    assert payload["input_files"][0] == {"name": "seed_payloads", "filename": "seed_payloads.json", "present": False}
    assert payload["request_metadata"]["request_count"] == 0
    assert payload["production_order_direct"]["status"] is None
    assert payload["shipment_comparison"]["categories"] == {}
    assert payload["next_actions"] == ["No immediate MVP analytics blockers detected in the deterministic smoke dataset."]
    assert (tmp_path / "summary.md").exists()
    assert "- **Top risks**: none" in (tmp_path / "summary.md").read_text(encoding="utf-8")
