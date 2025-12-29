from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.schemas.order_explanation import ArticleOrderExplanation, OrderProposalReason
from app.schemas.planning_health import ArticleHealthSummary
from app.services import article_dashboard


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


def test_article_dashboard_happy_path_all_blocks_present(client, db_session, monkeypatch):  # noqa: ARG001
    article_id = 123

    risk_entry = ArticleBundleRiskEntry(
        article_id=article_id,
        article_code="A123",
        bundle_type_id=10,
        bundle_type_name="BT",
        avg_daily_sales=1.0,
        total_available_bundles=5,
        days_of_cover=5.0,
        risk_level=BundleRiskLevel.CRITICAL,
        safety_stock_days=7,
        alert_threshold_days=14,
        overstock_threshold_days=42,
        explanation="risk",
    )

    order_entry = ArticleOrderExplanation(
        article_id=article_id,
        article_code="A123",
        reasons=[
            OrderProposalReason(
                article_id=article_id,
                article_code="A123",
                color_id=None,
                color_name=None,
                elastic_type_id=None,
                elastic_type_name=None,
                proposed_qty=10,
                base_deficit=10,
                strictness=1.0,
                adjusted_deficit=10.0,
                min_fabric_batch=None,
                min_elastic_batch=None,
                color_min_batch=None,
                total_available_before=0,
                forecast_horizon_days=30,
                final_order_qty=10,
                limiting_constraint="strictness",
                explanation="order",
            )
        ],
    )

    health_entry = ArticleHealthSummary(
        article_id=article_id,
        article_code="A123",
        worst_risk_level=BundleRiskLevel.CRITICAL,
        worst_risk_bundle_type_id=10,
        worst_risk_bundle_type_name="BT",
        days_of_cover=5.0,
        avg_daily_sales=1.0,
        total_available_bundles=5,
        total_final_order_qty=10,
        dominant_limiting_constraint="strictness",
        has_critical=True,
        has_warning=False,
    )

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [risk_entry]

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return [order_entry]

    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return [health_entry]

    monkeypatch.setattr(
        article_dashboard,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )

    resp = client.get("/api/v1/planning/article-dashboard/123")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["article_id"] == article_id
    assert body["risk"] is not None
    assert body["order"] is not None
    assert body["health"] is not None
    assert body["article_code"] == "A123"
    assert body["bundle_type_id"] == 10
    assert body["bundle_type_name"] == "BT"


def test_article_dashboard_partial_only_risk(client, db_session, monkeypatch):  # noqa: ARG001
    article_id = 777

    risk_entry = ArticleBundleRiskEntry(
        article_id=article_id,
        article_code="A777",
        bundle_type_id=20,
        bundle_type_name="BT2",
        avg_daily_sales=1.0,
        total_available_bundles=10,
        days_of_cover=10.0,
        risk_level=BundleRiskLevel.WARNING,
        safety_stock_days=7,
        alert_threshold_days=14,
        overstock_threshold_days=42,
        explanation="risk",
    )

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [risk_entry]

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        article_dashboard,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )

    resp = client.get("/api/v1/planning/article-dashboard/777")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["article_id"] == article_id
    assert body["risk"] is not None
    assert body["order"] is None
    assert body["health"] is None
    assert body["article_code"] == "A777"
    assert body["bundle_type_id"] == 20
    assert body["bundle_type_name"] == "BT2"


def test_article_dashboard_article_not_found(client, db_session, monkeypatch):  # noqa: ARG001
    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        article_dashboard,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )
    monkeypatch.setattr(
        article_dashboard,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )

    resp = client.get("/api/v1/planning/article-dashboard/9999")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["detail"] == "Article not found"
