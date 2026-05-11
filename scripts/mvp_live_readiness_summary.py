from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


REPORT_TYPE = "mvp_live_readiness"
SUMMARY_SCHEMA_VERSION = "1.0"

INPUT_FILES = {
    "request": "request.json",
    "readiness": "readiness.json",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    return payload if isinstance(payload, dict) else {}


def _category_text(categories: dict[str, int]) -> str:
    if not categories:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(categories.items()))


def _first_items(items: list[Any], limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "article_id": item.get("article_id"),
                "article_code": item.get("article_code"),
                "ready_for_from_wb": item.get("ready_for_from_wb"),
                "blocker": item.get("blocker"),
                "freshness_status": item.get("freshness_status"),
                "next_steps": item.get("next_steps") or [],
            }
        )
    return rows


def _input_files_summary(report_dir: Path, files: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "filename": filename,
            "present": (report_dir / filename).exists(),
        }
        for name, filename in files.items()
    ]


def _missing_input_files(input_files: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("filename"))
        for item in input_files
        if isinstance(item, dict) and not item.get("present")
    ]


def _validation_messages(artifact_status: str, missing_input_files: list[str]) -> list[str]:
    if artifact_status == "complete":
        return ["All expected MVP live readiness input files are present."]
    if missing_input_files:
        return [
            "MVP live readiness report is incomplete; restore missing input files: "
            + ", ".join(missing_input_files)
            + "."
        ]
    return ["MVP live readiness artifact completeness has not been evaluated for this in-memory summary."]


def _input_file_counts(input_files: list[dict[str, Any]], missing_input_files: list[str]) -> dict[str, int]:
    expected_input_file_count = len(input_files)
    missing_input_file_count = len(missing_input_files)
    return {
        "expected_input_file_count": expected_input_file_count,
        "present_input_file_count": expected_input_file_count - missing_input_file_count,
        "missing_input_file_count": missing_input_file_count,
    }


def build_summary(readiness_payload: dict[str, Any], request_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    items = readiness_payload.get("items")
    if not isinstance(items, list):
        items = []

    blockers = Counter(
        str(item.get("blocker"))
        for item in items
        if isinstance(item, dict) and item.get("blocker") is not None
    )
    next_steps = Counter(
        str(step)
        for item in items
        if isinstance(item, dict)
        for step in item.get("next_steps") or []
    )
    freshness = Counter(
        str(item.get("freshness_status"))
        for item in items
        if isinstance(item, dict) and item.get("freshness_status") is not None
    )

    return {
        "report_type": REPORT_TYPE,
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "artifact_status": "unknown",
        "missing_input_files": [],
        "expected_input_file_count": 0,
        "present_input_file_count": 0,
        "missing_input_file_count": 0,
        "validation_messages": _validation_messages("unknown", []),
        "request": request_payload or {},
        "input_files": [],
        "total_articles_considered": readiness_payload.get("total_articles_considered"),
        "ready_articles": readiness_payload.get("ready_articles"),
        "not_ready_articles": readiness_payload.get("not_ready_articles"),
        "blockers": dict(sorted(blockers.items())),
        "freshness_statuses": dict(sorted(freshness.items())),
        "next_steps": dict(sorted(next_steps.items())),
        "sample_items": _first_items(items),
    }


def render_markdown_summary(summary: dict[str, Any]) -> str:
    request = summary.get("request") or {}
    input_files = summary.get("input_files") or []
    lines = [
        "# MVP Live Readiness Summary",
        "",
        f"- **Report type**: `{summary.get('report_type')}`",
        f"- **Summary schema version**: `{summary.get('summary_schema_version')}`",
        f"- **Artifact status**: `{summary.get('artifact_status')}`",
        f"- **Expected input files**: `{summary.get('expected_input_file_count')}`",
        f"- **Present input files**: `{summary.get('present_input_file_count')}`",
        f"- **Missing input files count**: `{summary.get('missing_input_file_count')}`",
        f"- **Missing input files**: `{', '.join(summary.get('missing_input_files') or []) or 'none'}`",
        "",
        "## Validation",
        "",
    ]

    validation_messages = summary.get("validation_messages") or []
    if validation_messages:
        for message in validation_messages:
            lines.append(f"- **Validation**: {message}")
    else:
        lines.append("- **Validation**: none")

    lines.extend(
        [
        "",
        "## Request",
        "",
        f"- **Article ID**: `{request.get('article_id')}`",
        f"- **Limit**: `{request.get('limit')}`",
        f"- **Sales stale after days**: `{request.get('freshness_sales_stale_after_days')}`",
        f"- **Stock stale after days**: `{request.get('freshness_stock_stale_after_days')}`",
        "",
        "## Input files",
        "",
        ]
    )

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
                f"| {item.get('name')} | `{item.get('filename')}` | {item.get('present')} |"
            )
    else:
        lines.append("- **Input files**: none")

    lines.extend(
        [
        "",
        "## Result",
        "",
        f"- **Total articles considered**: `{summary.get('total_articles_considered')}`",
        f"- **Ready articles**: `{summary.get('ready_articles')}`",
        f"- **Not-ready articles**: `{summary.get('not_ready_articles')}`",
        f"- **Blockers**: `{_category_text(summary.get('blockers') or {})}`",
        f"- **Freshness statuses**: `{_category_text(summary.get('freshness_statuses') or {})}`",
        f"- **Next steps**: `{_category_text(summary.get('next_steps') or {})}`",
        "",
        "## Sample readiness items",
        "",
        ]
    )

    sample_items = summary.get("sample_items") or []
    if sample_items:
        lines.extend(
            [
                "| Article | Code | Ready | Blocker | Freshness | Next steps |",
                "|---:|---|---|---|---|---|",
            ]
        )
        for item in sample_items:
            if not isinstance(item, dict):
                continue
            steps = ", ".join(item.get("next_steps") or []) or "none"
            lines.append(
                f"| {item.get('article_id')} | {item.get('article_code')} | {item.get('ready_for_from_wb')} | "
                f"{item.get('blocker')} | {item.get('freshness_status')} | {steps} |"
            )
    else:
        lines.append("- **Sample readiness items**: none")

    lines.append("")
    return "\n".join(lines)


def write_summary(report_dir: Path) -> tuple[Path, Path]:
    readiness_path = report_dir / "readiness.json"
    request_path = report_dir / "request.json"
    readiness_payload = _read_json(readiness_path)
    request_payload = _read_json(request_path) if request_path.exists() else {}
    summary = build_summary(readiness_payload, request_payload=request_payload)
    input_files = _input_files_summary(report_dir, INPUT_FILES)
    missing_input_files = _missing_input_files(input_files)
    artifact_status = "complete" if not missing_input_files else "incomplete"
    input_file_counts = _input_file_counts(input_files, missing_input_files)
    summary["input_files"] = input_files
    summary["missing_input_files"] = missing_input_files
    summary.update(input_file_counts)
    summary["artifact_status"] = artifact_status
    summary["validation_messages"] = _validation_messages(artifact_status, missing_input_files)

    summary_json_path = report_dir / "summary.json"
    with summary_json_path.open("w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")

    summary_md_path = report_dir / "summary.md"
    summary_md_path.write_text(render_markdown_summary(summary), encoding="utf-8")
    return summary_json_path, summary_md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build summaries for an MVP live readiness report directory.")
    parser.add_argument("report_dir", help="Directory containing readiness.json.")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    if not report_dir.exists() or not report_dir.is_dir():
        raise SystemExit(f"report_dir does not exist or is not a directory: {report_dir}")

    summary_json_path, summary_md_path = write_summary(report_dir=report_dir)
    print(summary_json_path)
    print(summary_md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
