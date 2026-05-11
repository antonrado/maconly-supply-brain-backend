from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.json_schema_subset import assert_valid_schema
from scripts.build_mvp_report_verification_manifest import build_manifest
from scripts.mvp_first_analytics_summary import write_summary as write_first_analytics_summary
from scripts.mvp_live_readiness_summary import write_summary as write_live_readiness_summary


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas" / "reporting"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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

    assert_valid_schema(manifest, schema)


def test_mvp_report_verification_manifest_schema_rejects_unexpected_nested_report_key(tmp_path: Path) -> None:
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
    manifest["reports"]["first_analytics"]["unexpected"] = True
    schema = _load_schema("mvp_report_verification_manifest.schema.json")

    try:
        assert_valid_schema(manifest, schema)
    except ValueError as exc:
        assert "unexpected key 'unexpected'" in str(exc)
    else:
        raise AssertionError("expected verification manifest schema to reject an unexpected nested report key")
