from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.validate_mvp_report_summary_schema import validate_report_path


VERIFICATION_TYPE = "mvp_report_artifact_verification"
VERIFICATION_SCHEMA_VERSION = "1.0"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _report_entry(report_path: Path) -> dict[str, Any]:
    summary_path, schema_path = validate_report_path(report_path)
    summary = _read_json(summary_path)

    return {
        "report_dir": str(summary_path.parent),
        "summary_path": str(summary_path),
        "schema_path": str(schema_path),
        "report_type": summary.get("report_type"),
        "summary_schema_version": summary.get("summary_schema_version"),
        "artifact_status": summary.get("artifact_status"),
        "expected_input_file_count": summary.get("expected_input_file_count"),
        "present_input_file_count": summary.get("present_input_file_count"),
        "missing_input_file_count": summary.get("missing_input_file_count"),
        "missing_input_files": summary.get("missing_input_files") or [],
        "validation_messages": summary.get("validation_messages") or [],
    }


def build_manifest(first_analytics_report_path: Path, live_readiness_report_path: Path) -> dict[str, Any]:
    first_analytics = _report_entry(first_analytics_report_path)
    live_readiness = _report_entry(live_readiness_report_path)
    overall_artifact_status = (
        "complete"
        if first_analytics.get("artifact_status") == "complete"
        and live_readiness.get("artifact_status") == "complete"
        else "incomplete"
    )

    return {
        "verification_type": VERIFICATION_TYPE,
        "verification_schema_version": VERIFICATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verification_status": "ok",
        "overall_artifact_status": overall_artifact_status,
        "reports": {
            "first_analytics": first_analytics,
            "live_readiness": live_readiness,
        },
    }


def write_manifest(
    output_path: Path,
    first_analytics_report_path: Path,
    live_readiness_report_path: Path,
) -> Path:
    manifest = build_manifest(first_analytics_report_path, live_readiness_report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file_obj:
        json.dump(manifest, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a combined machine-readable verification manifest for MVP report artifacts."
    )
    parser.add_argument("first_analytics_report_path", help="Path to the first analytics report directory or summary.json.")
    parser.add_argument("live_readiness_report_path", help="Path to the live readiness report directory or summary.json.")
    parser.add_argument("output_path", help="Output path for verification.json.")
    args = parser.parse_args()

    try:
        output_path = write_manifest(
            output_path=Path(args.output_path),
            first_analytics_report_path=Path(args.first_analytics_report_path),
            live_readiness_report_path=Path(args.live_readiness_report_path),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
