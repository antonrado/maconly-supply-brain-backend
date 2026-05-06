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


def _value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _category_text(categories: dict[str, Any]) -> str:
    if not categories:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(categories.items()))


def render_markdown_summary(summary: dict[str, Any]) -> str:
    direct = summary.get("production_order_direct") or {}
    from_wb = summary.get("production_order_from_wb") or {}
    shipment = summary.get("shipment_comparison") or {}
    monitoring = summary.get("monitoring") or {}
    top_risks = monitoring.get("top_risks") or []
    if not isinstance(top_risks, list):
        top_risks = []

    lines = [
        "# MVP First Analytics Summary",
        "",
        f"- **Report directory**: `{_value(summary.get('report_dir'))}`",
        "",
        "## Production order",
        "",
        "| Source | Status | Article | Risk | Action | Units | Lines | Arrival status | Shortage before arrival |",
        "|---|---:|---:|---|---|---:|---:|---|---:|",
        (
            f"| Direct | {_value(direct.get('status'))} | {_value(direct.get('article_id'))} | "
            f"{_value(direct.get('risk_level'))} | {_value(direct.get('action'))} | "
            f"{_value(direct.get('total_units'))} | {_value(direct.get('line_count'))} | "
            f"{_value(direct.get('arrival_projection_status'))} | "
            f"{_value(direct.get('projected_shortage_before_arrival'))} |"
        ),
        (
            f"| From WB | {_value(from_wb.get('status'))} | {_value(from_wb.get('article_id'))} | "
            f"{_value(from_wb.get('risk_level'))} | {_value(from_wb.get('action'))} | "
            f"{_value(from_wb.get('total_units'))} | {_value(from_wb.get('line_count'))} | "
            f"{_value(from_wb.get('arrival_projection_status'))} | "
            f"{_value(from_wb.get('projected_shortage_before_arrival'))} |"
        ),
        "",
        "## Shipment comparison",
        "",
        f"- **Target date**: `{_value(shipment.get('target_date'))}`",
        f"- **WB arrival date**: `{_value(shipment.get('wb_arrival_date'))}`",
        f"- **Has divergence**: `{_value(shipment.get('has_divergence'))}`",
        f"- **Articles**: `{_value(shipment.get('article_count'))}` total, `{_value(shipment.get('divergent_article_count'))}` divergent",
        f"- **Categories**: `{_category_text(shipment.get('categories') or {})}`",
        f"- **Normalization**: `{_value(shipment.get('normalization_strategy'))}`",
        f"- **Canonical planning horizon days**: `{_value(shipment.get('canonical_planning_horizon_days'))}`",
        "",
        "## Monitoring",
        "",
        f"- **Overall status**: `{_value(monitoring.get('overall_status'))}`",
        f"- **Alerts**: `{_value(monitoring.get('critical_alerts'))}` critical, `{_value(monitoring.get('warning_alerts'))}` warning",
        f"- **Risks**: `{_category_text(monitoring.get('risks') or {})}`",
        f"- **Orders**: `{_category_text(monitoring.get('orders') or {})}`",
        f"- **Timeseries metrics**: `{', '.join(monitoring.get('timeseries_metrics') or []) or 'none'}`",
        "",
        "## Top risks",
        "",
    ]

    if top_risks:
        lines.extend(
            [
                "| Article | Code | Bundle | Risk | Days of cover | Final order qty |",
                "|---:|---|---|---|---:|---:|",
            ]
        )
        for item in top_risks:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| {_value(item.get('article_id'))} | {_value(item.get('article_code'))} | "
                f"{_value(item.get('bundle_type_name') or item.get('bundle_type_id'))} | "
                f"{_value(item.get('risk_level'))} | {_value(item.get('days_of_cover'))} | "
                f"{_value(item.get('final_order_qty'))} |"
            )
    else:
        lines.append("- **Top risks**: none")

    lines.append("")
    return "\n".join(lines)


def write_markdown_summary(report_dir: Path, summary: dict[str, Any]) -> Path:
    markdown_path = report_dir / "summary.md"
    markdown_path.write_text(render_markdown_summary(summary), encoding="utf-8")
    return markdown_path


def write_summary(report_dir: Path) -> Path:
    summary_path = report_dir / "summary.json"
    summary = build_summary(report_dir=report_dir)
    with summary_path.open("w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")
    write_markdown_summary(report_dir=report_dir, summary=summary)
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
