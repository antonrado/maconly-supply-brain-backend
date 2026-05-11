from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.json_schema_subset import assert_valid_schema


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "reporting"
SCHEMA_FILENAMES = {
    "mvp_first_analytics": "mvp_first_analytics_summary.schema.json",
    "mvp_live_readiness": "mvp_live_readiness_summary.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    with (SCHEMA_DIR / name).open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"schema must be a JSON object: {name}")
    return payload


def schema_path_for_report_type(report_type: str) -> Path:
    schema_filename = SCHEMA_FILENAMES.get(report_type)
    if not schema_filename:
        raise ValueError(f"unsupported report_type for summary schema validation: {report_type!r}")
    return SCHEMA_DIR / schema_filename


def validate_summary_payload(summary: dict[str, Any]) -> Path:
    report_type = summary.get("report_type")
    if not isinstance(report_type, str):
        raise ValueError("summary report_type must be a string")
    schema_path = schema_path_for_report_type(report_type)
    schema = load_schema(schema_path.name)
    assert_valid_schema(summary, schema)
    return schema_path


def validate_summary_file(summary_path: Path) -> Path:
    with summary_path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"summary must be a JSON object: {summary_path}")
    return validate_summary_payload(payload)


def resolve_summary_path(path: Path) -> Path:
    if path.is_dir():
        return path / "summary.json"
    return path


def validate_report_path(path: Path) -> tuple[Path, Path]:
    summary_path = resolve_summary_path(path)
    if not summary_path.exists() or not summary_path.is_file():
        raise ValueError(f"summary.json does not exist: {summary_path}")
    schema_path = validate_summary_file(summary_path)
    return summary_path, schema_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an MVP report summary.json against its static JSON Schema contract.")
    parser.add_argument("report_path", help="Path to a report directory or summary.json file.")
    args = parser.parse_args()

    try:
        summary_path, schema_path = validate_report_path(Path(args.report_path))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(summary_path)
    print(schema_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
