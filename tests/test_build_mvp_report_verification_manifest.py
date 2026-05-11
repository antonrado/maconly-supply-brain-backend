from __future__ import annotations

import json
from pathlib import Path

from scripts.build_mvp_report_verification_manifest import build_manifest, write_manifest
from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary


def test_build_manifest_collects_both_report_summaries(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    live_dir = tmp_path / "live"
    first_dir.mkdir()
    live_dir.mkdir()

    first_summary_path = write_first_analytics_summary(report_dir=first_dir)
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
    live_summary_path, _ = write_live_readiness_summary(live_dir)

    manifest = build_manifest(first_dir, live_summary_path)

    assert manifest["verification_type"] == "mvp_report_artifact_verification"
    assert manifest["verification_schema_version"] == "1.0"
    assert manifest["verification_status"] == "ok"
    assert manifest["overall_artifact_status"] == "incomplete"
    assert manifest["reports"]["first_analytics"]["summary_path"] == str(first_summary_path)
    assert manifest["reports"]["first_analytics"]["report_type"] == "mvp_first_analytics"
    assert manifest["reports"]["first_analytics"]["artifact_status"] == "incomplete"
    assert manifest["reports"]["live_readiness"]["summary_path"] == str(live_summary_path)
    assert manifest["reports"]["live_readiness"]["report_type"] == "mvp_live_readiness"
    assert manifest["reports"]["live_readiness"]["artifact_status"] == "complete"


def test_write_manifest_writes_json_file(tmp_path: Path) -> None:
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

    output_path = tmp_path / "verification" / "verification.json"
    written_path = write_manifest(output_path, first_dir, live_dir)

    assert written_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["verification_status"] == "ok"
    assert payload["reports"]["first_analytics"]["missing_input_file_count"] == 9
    assert payload["reports"]["live_readiness"]["missing_input_file_count"] == 0
