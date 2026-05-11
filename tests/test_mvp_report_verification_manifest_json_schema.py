from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.build_mvp_report_verification_manifest import build_manifest
from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "reporting"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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
    raise AssertionError(f"Unsupported schema type: {expected_type}")


def _assert_valid_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "const" in schema:
        assert value == schema["const"], f"{path}: expected const {schema['const']!r}, got {value!r}"

    if "enum" in schema:
        assert value in schema["enum"], f"{path}: expected one of {schema['enum']!r}, got {value!r}"

    expected_type = schema.get("type")
    if expected_type is not None:
        allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
        assert any(_matches_type(value, item) for item in allowed_types), (
            f"{path}: expected type {allowed_types!r}, got {type(value).__name__}"
        )

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            assert key in value, f"{path}: missing required key {key!r}"

        properties = schema.get("properties") or {}
        additional_properties = schema.get("additionalProperties", True)

        for key, item in value.items():
            if key in properties:
                _assert_valid_schema(item, properties[key], f"{path}.{key}")
                continue
            if additional_properties is False:
                raise AssertionError(f"{path}: unexpected key {key!r}")
            if isinstance(additional_properties, dict):
                _assert_valid_schema(item, additional_properties, f"{path}.{key}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _assert_valid_schema(item, item_schema, f"{path}[{index}]")


def test_mvp_report_verification_manifest_matches_json_schema(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    live_dir = tmp_path / "live"
    first_dir.mkdir()
    live_dir.mkdir()

    write_first_analytics_summary(report_dir=first_dir)
    (live_dir / "readiness.json").write_text(
        json.dumps(
            {
                "total_articles_considered": 0,
                "ready_articles": 0,
                "not_ready_articles": 0,
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    (live_dir / "request.json").write_text(
        json.dumps(
            {
                "article_id": 10,
                "limit": 1,
                "freshness_sales_stale_after_days": 5,
                "freshness_stock_stale_after_days": 6,
            }
        ),
        encoding="utf-8",
    )
    write_live_readiness_summary(live_dir)

    manifest = build_manifest(first_dir, live_dir)
    schema = _load_schema("mvp_report_verification_manifest.schema.json")

    _assert_valid_schema(manifest, schema)
