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

INPUT_FILES = {
    "seed_payloads": "seed_payloads.json",
    "requests": "requests.json",
    "planning_core_health": "planning_core_health.json",
    **REPORT_FILES,
}


def _request_metadata_summary(payload: dict[str, Any]) -> dict[str, Any]:
    requests = payload.get("requests")
    if not isinstance(requests, list):
        requests = []

    return {
        "generated_at": payload.get("generated_at"),
        "base_url": payload.get("base_url"),
        "request_count": len(requests),
        "requests": [
            {
                "name": item.get("name"),
                "method": item.get("method"),
                "url": item.get("url"),
                "has_body": isinstance(item.get("body"), dict),
            }
            for item in requests
            if isinstance(item, dict)
        ],
    }


def _input_files_summary(report_dir: Path, files: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "filename": filename,
            "present": (report_dir / filename).exists(),
        }
        for name, filename in files.items()
    ]


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


def _derive_next_actions(summary: dict[str, Any]) -> list[str]:
    direct = summary.get("production_order_direct") or {}
    from_wb = summary.get("production_order_from_wb") or {}
    shipment = summary.get("shipment_comparison") or {}
    monitoring = summary.get("monitoring") or {}

    actions: list[str] = []
    direct_risk = direct.get("risk_level")
    from_wb_risk = from_wb.get("risk_level")
    if direct_risk in {"warning", "critical"} or from_wb_risk in {"warning", "critical"}:
        actions.append(
            "Review production-order recommendations: "
            f"direct risk={_value(direct_risk)}, direct units={_value(direct.get('total_units'))}; "
            f"from-WB risk={_value(from_wb_risk)}, from-WB units={_value(from_wb.get('total_units'))}."
        )

    arrival_statuses = {
        direct.get("arrival_projection_status"),
        from_wb.get("arrival_projection_status"),
    }
    if "shortage_before_arrival" in arrival_statuses:
        actions.append(
            "Prioritize shortage-before-arrival review: inspect arrival projection and decide whether inbound/order timing must be accelerated."
        )

    if shipment.get("has_divergence"):
        actions.append(
            "Review shipment comparison divergences before changing operator flow: "
            f"{_category_text(shipment.get('categories') or {})}."
        )

    if monitoring.get("overall_status") in {"warning", "critical"} or monitoring.get("top_risk_count", 0):
        actions.append(
            "Inspect monitoring dashboard and risk-focus list: "
            f"overall={_value(monitoring.get('overall_status'))}, top_risk_count={_value(monitoring.get('top_risk_count'))}."
        )

    if not actions:
        actions.append("No immediate MVP analytics blockers detected in the deterministic smoke dataset.")

    return actions


def build_summary(report_dir: Path) -> dict[str, Any]:
    payloads = {name: _read_json(report_dir / filename) for name, filename in REPORT_FILES.items()}
    request_metadata = _read_json(report_dir / "requests.json")
    summary = {
        "report_dir": str(report_dir),
        "input_files": _input_files_summary(report_dir, INPUT_FILES),
        "request_metadata": _request_metadata_summary(request_metadata),
        "production_order_direct": _recommendation_summary(payloads["production_order_direct"]),
        "production_order_from_wb": _recommendation_summary(payloads["production_order_from_wb"]),
        "shipment_comparison": _shipment_comparison_summary(payloads["shipment_comparison"]),
        "monitoring": _monitoring_summary(
            payloads["monitoring_dashboard"],
            payloads["monitoring_risk_focus"],
            payloads["monitoring_timeseries"],
        ),
    }
    summary["next_actions"] = _derive_next_actions(summary)
    return summary


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
    request_metadata = summary.get("request_metadata") or {}
    input_files = summary.get("input_files") or []
    next_actions = summary.get("next_actions") or []
    top_risks = monitoring.get("top_risks") or []
    if not isinstance(top_risks, list):
        top_risks = []
    if not isinstance(next_actions, list):
        next_actions = []

    lines = [
        "# MVP First Analytics Summary",
        "",
        f"- **Report directory**: `{_value(summary.get('report_dir'))}`",
        f"- **Request count**: `{_value(request_metadata.get('request_count'))}`",
        f"- **Base URL**: `{_value(request_metadata.get('base_url'))}`",
        "",
        "## Input files",
        "",
    ]

    if input_files:
        lines.extend(
            [
                "| Name | Filename | Present |",
                "|---|---|---|",
            ]
        )
        for item in input_files:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| {_value(item.get('name'))} | `{_value(item.get('filename'))}` | {_value(item.get('present'))} |"
            )
    else:
        lines.append("- **Input files**: none")

    lines.extend(
        [
        "",
        "## Requests",
        "",
        ]
    )

    requests = request_metadata.get("requests") or []
    if requests:
        lines.extend(
            [
                "| Name | Method | Has body |",
                "|---|---|---|",
            ]
        )
        for item in requests:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| {_value(item.get('name'))} | {_value(item.get('method'))} | {_value(item.get('has_body'))} |"
            )
    else:
        lines.append("- **Requests**: none")

    lines.extend(
        [
        "",
        "## Next actions",
        "",
        ]
    )

    if next_actions:
        for action in next_actions:
            lines.append(f"- **Action**: {action}")
    else:
        lines.append("- **Action**: n/a")

    lines.extend(
        [
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
        ]
    )

    lines.extend(
        [
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
    )

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
