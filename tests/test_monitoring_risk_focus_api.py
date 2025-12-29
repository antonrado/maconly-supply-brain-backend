from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.services import monitoring_risk_focus


@pytest.fixture
def client(db_session):
    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_entry(
    article_id: int,
    article_code: str,
    bundle_type_id: int,
    bundle_type_name: str,
    risk_level: BundleRiskLevel,
) -> ArticleBundleRiskEntry:
    return ArticleBundleRiskEntry(
        article_id=article_id,
        article_code=article_code,
        bundle_type_id=bundle_type_id,
        bundle_type_name=bundle_type_name,
        avg_daily_sales=1.0,
        total_available_bundles=10,
        days_of_cover=5.0,
        risk_level=risk_level,
        safety_stock_days=7,
        alert_threshold_days=14,
        overstock_threshold_days=42,
        explanation="",
    )


def test_monitoring_risk_focus_basic_sorting(client, db_session, monkeypatch):  # noqa: ARG001
    # Two CRITICAL, one WARNING, one OK
    e1 = _make_entry(article_id=2, article_code="A2", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.CRITICAL)
    e2 = _make_entry(article_id=1, article_code="A1", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.CRITICAL)
    e3 = _make_entry(article_id=3, article_code="A3", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.WARNING)
    e4 = _make_entry(article_id=4, article_code="A4", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.OK)

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [e1, e2, e3, e4]

    monkeypatch.setattr(
        monitoring_risk_focus,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )

    resp = client.get(
        "/api/v1/planning/monitoring/risk-focus",
        params={"limit": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 3

    # First two are CRITICAL, ordered by article_id (1 then 2), then WARNING
    assert [it["risk_level"] for it in items] == ["critical", "critical", "warning"]
    assert [it["article_id"] for it in items[:2]] == [1, 2]


def test_monitoring_risk_focus_empty_portfolio(client, db_session, monkeypatch):  # noqa: ARG001
    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        monitoring_risk_focus,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )

    resp = client.get("/api/v1/planning/monitoring/risk-focus")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": []}


def test_monitoring_risk_focus_tie_breaker_stability(client, db_session, monkeypatch):  # noqa: ARG001
    # Several WARNING entries with different article_id/bundle_type_id to test tie-breaker
    e1 = _make_entry(article_id=3, article_code="C", bundle_type_id=2, bundle_type_name="BT2", risk_level=BundleRiskLevel.WARNING)
    e2 = _make_entry(article_id=1, article_code="A", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.WARNING)
    e3 = _make_entry(article_id=2, article_code="B", bundle_type_id=1, bundle_type_name="BT1", risk_level=BundleRiskLevel.WARNING)

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [e1, e2, e3]

    monkeypatch.setattr(
        monitoring_risk_focus,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )

    resp1 = client.get("/api/v1/planning/monitoring/risk-focus")
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()
    items1 = body1["items"]

    # Sorted by risk priority (all WARNING) then by article_id, bundle_type_id, article_code
    assert [it["article_id"] for it in items1] == [1, 2, 3]

    # Second call should produce the same stable ordering
    resp2 = client.get("/api/v1/planning/monitoring/risk-focus")
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    items2 = body2["items"]

    assert [it["article_id"] for it in items2] == [1, 2, 3]
