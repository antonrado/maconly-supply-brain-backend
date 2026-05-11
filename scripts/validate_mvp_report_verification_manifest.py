from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "reporting" / "mvp_report_verification_manifest.schema.json"


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"schema must be a JSON object: {SCHEMA_PATH}")
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


def resolve_manifest_path(path: Path) -> Path:
    if path.is_dir():
        return path / "verification.json"
    return path


def validate_manifest_file(manifest_path: Path) -> Path:
    with manifest_path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"verification manifest must be a JSON object: {manifest_path}")
    assert_valid_schema(payload, load_schema())
    return SCHEMA_PATH


def validate_manifest_path(path: Path) -> tuple[Path, Path]:
    manifest_path = resolve_manifest_path(path)
    if not manifest_path.exists() or not manifest_path.is_file():
        raise ValueError(f"verification.json does not exist: {manifest_path}")
    schema_path = validate_manifest_file(manifest_path)
    return manifest_path, schema_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a verification.json file against its static JSON Schema contract.")
    parser.add_argument("manifest_path", help="Path to a verification artifact directory or verification.json file.")
    args = parser.parse_args()

    try:
        manifest_path, schema_path = validate_manifest_path(Path(args.manifest_path))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(manifest_path)
    print(schema_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
