from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORT_FILES = {
    "production_order_direct": "production_order_direct.json",
    "production_order_from_wb": "production_order_from_wb.json",
    "shipment_comparison": "shipment_comparison.json",
    "monitoring_dashboard": "monitoring_dashboard.json",
    "monitoring_risk_focus": "monitoring_risk_focus.json",
    "monitoring_timeseries": "monitoring_timeseries.json",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    return payload if isinstance(payload, dict) else {}


def _recommendation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    recommendation = payload.get("recommendation")
    if not isinstance(recommendation, dict):
        recommendation = {}
    arrival_projection = payload.get("arrival_projection")
    if not isinstance(arrival_projection, dict):
        arrival_projection = {}

    return {
        "status": payload.get("status"),
        "article_id": payload.get("article_id"),
        "risk_level": payload.get("risk_level"),
        "days_of_cover_estimate": payload.get("days_of_cover_estimate"),
        "action": recommendation.get("action"),
        "total_units": recommendation.get("total_units"),
        "line_count": len(recommendation.get("lines") or []),
        "arrival_projection_status": arrival_projection.get("status"),
        "projected_shortage_before_arrival": arrival_projection.get("projected_shortage_before_arrival"),
    }


def _shipment_comparison_summary(payload: dict[str, Any]) -> dict[str, Any]:
    divergence_summary = payload.get("divergence_summary")
    if not isinstance(divergence_summary, dict):
        divergence_summary = {}
    scope_normalization = payload.get("scope_normalization")
    if not isinstance(scope_normalization, dict):
        scope_normalization = {}

    return {
        "target_date": payload.get("target_date"),
        "wb_arrival_date": payload.get("wb_arrival_date"),
        "has_divergence": divergence_summary.get("has_divergence"),
        "article_count": divergence_summary.get("article_count"),
        "divergent_article_count": divergence_summary.get("divergent_article_count"),
        "categories": divergence_summary.get("categories") or {},
        "normalization_strategy": scope_normalization.get("normalization_strategy"),
        "canonical_planning_horizon_days": scope_normalization.get("canonical_planning_horizon_days"),
    }


def _monitoring_summary(dashboard: dict[str, Any], risk_focus: dict[str, Any], timeseries: dict[str, Any]) -> dict[str, Any]:
    status = dashboard.get("status")
    if not isinstance(status, dict):
        status = {}
    snapshot = dashboard.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    risks = snapshot.get("risks")
    if not isinstance(risks, dict):
        risks = {}
    orders = snapshot.get("orders")
    if not isinstance(orders, dict):
        orders = {}
    risk_items = risk_focus.get("items")
    if not isinstance(risk_items, list):
        risk_items = []
    series_items = timeseries.get("items")
    if not isinstance(series_items, list):
        series_items = []

    return {
        "overall_status": status.get("overall_status"),
        "critical_alerts": status.get("critical_alerts"),
        "warning_alerts": status.get("warning_alerts"),
        "risks": risks,
        "orders": orders,
        "top_risk_count": len(risk_items),
        "top_risks": risk_items[:5],
        "timeseries_metrics": [item.get("metric") for item in series_items if isinstance(item, dict)],
    }


def build_summary(report_dir: Path) -> dict[str, Any]:
    payloads = {name: _read_json(report_dir / filename) for name, filename in REPORT_FILES.items()}
    return {
        "report_dir": str(report_dir),
        "production_order_direct": _recommendation_summary(payloads["production_order_direct"]),
        "production_order_from_wb": _recommendation_summary(payloads["production_order_from_wb"]),
        "shipment_comparison": _shipment_comparison_summary(payloads["shipment_comparison"]),
        "monitoring": _monitoring_summary(
            payloads["monitoring_dashboard"],
            payloads["monitoring_risk_focus"],
            payloads["monitoring_timeseries"],
        ),
    }


def write_summary(report_dir: Path) -> Path:
    summary_path = report_dir / "summary.json"
    summary = build_summary(report_dir=report_dir)
    with summary_path.open("w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build summary.json for an MVP first-analytics report directory.")
    parser.add_argument("report_dir", help="Directory containing mvp-first-analytics JSON response files.")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    if not report_dir.exists() or not report_dir.is_dir():
        raise SystemExit(f"report_dir does not exist or is not a directory: {report_dir}")

    summary_path = write_summary(report_dir=report_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
