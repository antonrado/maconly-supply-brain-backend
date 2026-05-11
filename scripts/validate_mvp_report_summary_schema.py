from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


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
    raise ValueError(f"unsupported schema type: {expected_type}")


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
    raise ValueError(f"unsupported schema format: {expected_format}")


def assert_valid_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path}: expected const {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: expected one of {schema['enum']!r}, got {value!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(value, item) for item in allowed_types):
            raise ValueError(f"{path}: expected type {allowed_types!r}, got {type(value).__name__}")

    expected_format = schema.get("format")
    if expected_format is not None and not _matches_format(value, expected_format):
        raise ValueError(f"{path}: expected format {expected_format!r}, got {value!r}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise ValueError(f"{path}: missing required key {key!r}")

        properties = schema.get("properties") or {}
        additional_properties = schema.get("additionalProperties", True)

        for key, item in value.items():
            if key in properties:
                assert_valid_schema(item, properties[key], f"{path}.{key}")
                continue
            if additional_properties is False:
                raise ValueError(f"{path}: unexpected key {key!r}")
            if isinstance(additional_properties, dict):
                assert_valid_schema(item, additional_properties, f"{path}.{key}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                assert_valid_schema(item, item_schema, f"{path}[{index}]")


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
