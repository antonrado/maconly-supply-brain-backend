from __future__ import annotations

import datetime as dt
from typing import Any


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
