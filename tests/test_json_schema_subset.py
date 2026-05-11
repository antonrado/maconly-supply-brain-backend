from __future__ import annotations

from scripts.json_schema_subset import assert_valid_schema


def test_assert_valid_schema_accepts_supported_nested_subset() -> None:
    payload = {
        "kind": "example",
        "generated_at": "2030-01-01T00:00:00+00:00",
        "target_date": "2030-01-02",
        "items": [
            {"name": "alpha", "count": 1},
            {"name": "beta", "count": 2},
        ],
        "meta": {"status": "ok"},
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "generated_at", "target_date", "items", "meta"],
        "properties": {
            "kind": {"const": "example"},
            "generated_at": {"type": "string", "format": "date-time"},
            "target_date": {"type": "string", "format": "date"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "count"],
                    "properties": {
                        "name": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                },
            },
            "meta": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
    }

    assert_valid_schema(payload, schema)


def test_assert_valid_schema_rejects_invalid_datetime_format() -> None:
    try:
        assert_valid_schema("not-a-datetime", {"type": "string", "format": "date-time"})
    except ValueError as exc:
        assert "expected format 'date-time'" in str(exc)
    else:
        raise AssertionError("expected invalid date-time format to be rejected")


def test_assert_valid_schema_rejects_invalid_date_format() -> None:
    try:
        assert_valid_schema("2030-99-99", {"type": "string", "format": "date"})
    except ValueError as exc:
        assert "expected format 'date'" in str(exc)
    else:
        raise AssertionError("expected invalid date format to be rejected")


def test_assert_valid_schema_rejects_unexpected_key_when_additional_properties_false() -> None:
    try:
        assert_valid_schema(
            {"name": "alpha", "extra": True},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        )
    except ValueError as exc:
        assert "unexpected key 'extra'" in str(exc)
    else:
        raise AssertionError("expected unexpected key to be rejected")


def test_assert_valid_schema_rejects_unsupported_format() -> None:
    try:
        assert_valid_schema("alpha", {"type": "string", "format": "email"})
    except ValueError as exc:
        assert "unsupported schema format: email" in str(exc)
    else:
        raise AssertionError("expected unsupported schema format to be rejected")


def test_assert_valid_schema_rejects_boolean_for_integer_type() -> None:
    try:
        assert_valid_schema(True, {"type": "integer"})
    except ValueError as exc:
        assert "expected type ['integer']" in str(exc)
    else:
        raise AssertionError("expected boolean to be rejected for integer type")


def test_assert_valid_schema_rejects_boolean_for_number_type() -> None:
    try:
        assert_valid_schema(False, {"type": "number"})
    except ValueError as exc:
        assert "expected type ['number']" in str(exc)
    else:
        raise AssertionError("expected boolean to be rejected for number type")


def test_assert_valid_schema_rejects_unsupported_schema_type() -> None:
    try:
        assert_valid_schema("alpha", {"type": "uuid"})
    except ValueError as exc:
        assert "unsupported schema type: uuid" in str(exc)
    else:
        raise AssertionError("expected unsupported schema type to be rejected")
