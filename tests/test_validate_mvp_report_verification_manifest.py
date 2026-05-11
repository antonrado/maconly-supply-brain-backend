from __future__ import annotations

import json
from pathlib import Path

from scripts.build_mvp_report_verification_manifest import write_manifest
from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary
from scripts.validate_mvp_report_verification_manifest import validate_manifest_file, validate_manifest_path


def test_validate_manifest_file_accepts_verification_manifest(tmp_path: Path) -> None:
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

    manifest_path = tmp_path / "verification.json"
    write_manifest(manifest_path, first_dir, live_dir)

    schema_path = validate_manifest_file(manifest_path)

    assert schema_path.name == "mvp_report_verification_manifest.schema.json"


def test_validate_manifest_path_accepts_verification_directory(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    live_dir = tmp_path / "live"
    verification_dir = tmp_path / "verification"
    first_dir.mkdir()
    live_dir.mkdir()
    verification_dir.mkdir()

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

    manifest_path = verification_dir / "verification.json"
    write_manifest(manifest_path, first_dir, live_dir)

    resolved_manifest_path, schema_path = validate_manifest_path(verification_dir)

    assert resolved_manifest_path == manifest_path
    assert schema_path.name == "mvp_report_verification_manifest.schema.json"


def test_validate_manifest_file_rejects_missing_required_key(tmp_path: Path) -> None:
    manifest_path = tmp_path / "verification.json"
    manifest_path.write_text(
        json.dumps(
            {
                "verification_type": "mvp_report_artifact_verification",
                "verification_schema_version": "1.0",
                "generated_at": "2030-01-01T00:00:00+00:00",
                "verification_status": "ok",
                "overall_artifact_status": "complete"
            }
        ),
        encoding="utf-8",
    )

    try:
        validate_manifest_file(manifest_path)
    except ValueError as exc:
        assert "missing required key 'reports'" in str(exc)
    else:
        raise AssertionError("expected validate_manifest_file to reject a manifest without reports")


def test_validate_manifest_path_rejects_directory_without_verification_json(tmp_path: Path) -> None:
    try:
        validate_manifest_path(tmp_path)
    except ValueError as exc:
        assert "verification.json does not exist" in str(exc)
    else:
        raise AssertionError("expected validate_manifest_path to reject a directory without verification.json")


def test_validate_manifest_file_rejects_invalid_generated_at_datetime(tmp_path: Path) -> None:
    manifest_path = tmp_path / "verification.json"
    manifest_path.write_text(
        json.dumps(
            {
                "verification_type": "mvp_report_artifact_verification",
                "verification_schema_version": "1.0",
                "generated_at": "not-a-datetime",
                "verification_status": "ok",
                "overall_artifact_status": "complete",
                "reports": {
                    "first_analytics": {
                        "report_dir": "x",
                        "summary_path": "x",
                        "schema_path": "x",
                        "report_type": "mvp_first_analytics",
                        "summary_schema_version": "1.1",
                        "artifact_status": "complete",
                        "expected_input_file_count": 1,
                        "present_input_file_count": 1,
                        "missing_input_file_count": 0,
                        "missing_input_files": [],
                        "validation_messages": []
                    },
                    "live_readiness": {
                        "report_dir": "x",
                        "summary_path": "x",
                        "schema_path": "x",
                        "report_type": "mvp_live_readiness",
                        "summary_schema_version": "1.1",
                        "artifact_status": "complete",
                        "expected_input_file_count": 1,
                        "present_input_file_count": 1,
                        "missing_input_file_count": 0,
                        "missing_input_files": [],
                        "validation_messages": []
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        validate_manifest_file(manifest_path)
    except ValueError as exc:
        assert "expected format 'date-time'" in str(exc)
    else:
        raise AssertionError("expected validate_manifest_file to reject an invalid generated_at date-time")


def test_validate_manifest_file_rejects_unexpected_nested_report_key(tmp_path: Path) -> None:
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

    manifest_path = tmp_path / "verification.json"
    write_manifest(manifest_path, first_dir, live_dir)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["reports"]["first_analytics"]["unexpected"] = True
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_manifest_file(manifest_path)
    except ValueError as exc:
        assert "unexpected key 'unexpected'" in str(exc)
    else:
        raise AssertionError("expected validate_manifest_file to reject an unexpected nested report key")
