from __future__ import annotations

import json
from pathlib import Path

from scripts.build_mvp_report_verification_manifest import write_manifest
from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary
from scripts.validate_mvp_report_verification_manifest import validate_manifest_file


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
