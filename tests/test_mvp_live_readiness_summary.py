from __future__ import annotations

import json

from scripts.mvp_live_readiness_summary import build_summary, render_markdown_summary, write_summary


def test_build_summary_counts_blockers_next_steps_and_freshness():
    payload = {
        "total_articles_considered": 3,
        "ready_articles": 1,
        "not_ready_articles": 2,
        "items": [
            {
                "article_id": 1,
                "article_code": "READY",
                "ready_for_from_wb": True,
                "blocker": None,
                "freshness_status": "fresh",
                "next_steps": [],
            },
            {
                "article_id": 2,
                "article_code": "NO-SALES",
                "ready_for_from_wb": False,
                "blocker": "no_wb_sales_data",
                "freshness_status": "missing_sales_data",
                "next_steps": ["run_wb_sales_daily_sync_live"],
            },
            {
                "article_id": 3,
                "article_code": "NO-STOCK",
                "ready_for_from_wb": False,
                "blocker": "no_wb_stock_data",
                "freshness_status": "missing_stock_data",
                "next_steps": ["run_wb_stock_sync_live"],
            },
        ],
    }

    request = {
        "article_id": 2,
        "limit": 20,
        "freshness_sales_stale_after_days": 3,
        "freshness_stock_stale_after_days": 4,
    }

    summary = build_summary(payload, request_payload=request)

    assert summary["request"] == request
    assert summary["total_articles_considered"] == 3
    assert summary["ready_articles"] == 1
    assert summary["not_ready_articles"] == 2
    assert summary["blockers"] == {"no_wb_sales_data": 1, "no_wb_stock_data": 1}
    assert summary["freshness_statuses"] == {
        "fresh": 1,
        "missing_sales_data": 1,
        "missing_stock_data": 1,
    }
    assert summary["next_steps"] == {
        "run_wb_sales_daily_sync_live": 1,
        "run_wb_stock_sync_live": 1,
    }
    assert len(summary["sample_items"]) == 3

    markdown = render_markdown_summary(summary)
    assert "# MVP Live Readiness Summary" in markdown
    assert "- **Article ID**: `2`" in markdown
    assert "- **Limit**: `20`" in markdown
    assert "- **Blockers**: `no_wb_sales_data=1, no_wb_stock_data=1`" in markdown
    assert "| 2 | NO-SALES | False | no_wb_sales_data | missing_sales_data | run_wb_sales_daily_sync_live |" in markdown


def test_write_summary_writes_json_and_markdown(tmp_path):
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

    summary_json, summary_md = write_summary(tmp_path)

    assert summary_json == tmp_path / "summary.json"
    assert summary_md == tmp_path / "summary.md"
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["request"]["article_id"] == 10
    assert payload["blockers"] == {}
    assert "Sample readiness items" in summary_md.read_text(encoding="utf-8")
