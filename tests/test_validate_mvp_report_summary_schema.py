from __future__ import annotations

import json
from pathlib import Path

from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary
from scripts.validate_mvp_report_summary_schema import validate_report_path, validate_summary_payload


SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "reporting"


def test_validate_report_path_accepts_first_analytics_directory(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)

    resolved_summary_path, schema_path = validate_report_path(tmp_path)

    assert resolved_summary_path == summary_path
    assert schema_path == SCHEMA_DIR / "mvp_first_analytics_summary.schema.json"


def test_validate_report_path_accepts_live_readiness_summary_file(tmp_path: Path) -> None:
    (tmp_path / "readiness.json").write_text(
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
    (tmp_path / "request.json").write_text(
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
    summary_path, _ = write_live_readiness_summary(tmp_path)

    resolved_summary_path, schema_path = validate_report_path(summary_path)

    assert resolved_summary_path == summary_path
    assert schema_path == SCHEMA_DIR / "mvp_live_readiness_summary.schema.json"


def test_validate_report_path_rejects_missing_summary_file_path(tmp_path: Path) -> None:
    missing_summary_path = tmp_path / "summary.json"

    try:
        validate_report_path(missing_summary_path)
    except ValueError as exc:
        assert "summary.json does not exist" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a missing summary.json file path")


def test_validate_report_path_rejects_directory_without_summary_json(tmp_path: Path) -> None:
    missing_summary_dir = tmp_path / "missing-summary"
    missing_summary_dir.mkdir()

    try:
        validate_report_path(missing_summary_dir)
    except ValueError as exc:
        assert "summary.json does not exist" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a directory without summary.json")


def test_validate_report_path_rejects_non_object_json_payload(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "summary must be a JSON object" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a non-object summary payload")


def test_validate_report_path_rejects_unknown_report_type(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "report_type": "unexpected_report",
                "summary_schema_version": "1.1",
            }
        ),
        encoding="utf-8",
    )

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "unsupported report_type" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject an unknown report_type")


def test_validate_summary_payload_rejects_non_string_report_type() -> None:
    try:
        validate_summary_payload({"report_type": 1})
    except ValueError as exc:
        assert "summary report_type must be a string" in str(exc)
    else:
        raise AssertionError("expected validate_summary_payload to reject a non-string report_type")


def test_validate_summary_payload_rejects_unsupported_report_type() -> None:
    try:
        validate_summary_payload({"report_type": "unexpected_report"})
    except ValueError as exc:
        assert "unsupported report_type for summary schema validation" in str(exc)
    else:
        raise AssertionError("expected validate_summary_payload to reject an unsupported report_type")


def test_validate_report_path_rejects_invalid_generated_at_datetime(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["request_metadata"]["generated_at"] = "not-a-datetime"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "expected format 'date-time'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject an invalid generated_at date-time")


def test_validate_report_path_rejects_invalid_shipment_comparison_date(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["shipment_comparison"]["target_date"] = "2026-99-99"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "expected format 'date'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject an invalid shipment comparison date")


def test_validate_report_path_rejects_unexpected_top_level_key(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "unexpected key 'unexpected'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject an unexpected top-level key")


def test_validate_report_path_rejects_missing_required_top_level_key(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    del payload["next_actions"]
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "missing required key 'next_actions'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a missing required top-level key")


def test_validate_report_path_rejects_first_analytics_missing_required_request_field(tmp_path: Path) -> None:
    summary_path = write_first_analytics_summary(report_dir=tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    del payload["production_order_direct"]["status"]
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "missing required key 'status'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject first-analytics nested data missing status")


def test_validate_report_path_rejects_live_readiness_unexpected_top_level_key(tmp_path: Path) -> None:
    (tmp_path / "readiness.json").write_text(
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
    (tmp_path / "request.json").write_text(
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
    summary_path, _ = write_live_readiness_summary(tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "unexpected key 'unexpected'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject an unexpected live-readiness top-level key")


def test_validate_report_path_rejects_live_readiness_missing_required_top_level_key(tmp_path: Path) -> None:
    (tmp_path / "readiness.json").write_text(
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
    (tmp_path / "request.json").write_text(
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
    summary_path, _ = write_live_readiness_summary(tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    del payload["sample_items"]
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "missing required key 'sample_items'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a live-readiness summary missing sample_items")


def test_validate_report_path_rejects_live_readiness_missing_required_sample_item_field(tmp_path: Path) -> None:
    (tmp_path / "readiness.json").write_text(
        json.dumps(
            {
                "total_articles_considered": 1,
                "ready_articles": 1,
                "not_ready_articles": 0,
                "items": [
                    {
                        "article_id": 10,
                        "article_code": "READY",
                        "ready_for_from_wb": True,
                        "blocker": None,
                        "freshness_status": "fresh",
                        "next_steps": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "request.json").write_text(
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
    summary_path, _ = write_live_readiness_summary(tmp_path)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    del payload["sample_items"][0]["freshness_status"]
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_report_path(summary_path)
    except ValueError as exc:
        assert "missing required key 'freshness_status'" in str(exc)
    else:
        raise AssertionError("expected validate_report_path to reject a live-readiness sample item missing freshness_status")
