from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.schemas.order_explanation import ArticleOrderExplanation, OrderProposalReason
from app.services import planning_health


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


def test_health_portfolio_happy_path_single_article(client, db_session, monkeypatch):
    article_id = 1
    article_code = "ART-1"

    risk_entry = ArticleBundleRiskEntry(
        article_id=article_id,
        article_code=article_code,
        bundle_type_id=10,
        bundle_type_name="BT-10",
        avg_daily_sales=2.5,
        total_available_bundles=50,
        days_of_cover=20.0,
        risk_level=BundleRiskLevel.WARNING,
        safety_stock_days=7,
        alert_threshold_days=14,
        overstock_threshold_days=42,
        explanation="test",
    )

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [risk_entry]

    reason = OrderProposalReason(
        article_id=article_id,
        article_code=article_code,
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
        forecast_horizon_days=None,
        final_order_qty=30,
        limiting_constraint="strictness",
        explanation="x",
    )

    explanation = ArticleOrderExplanation(
        article_id=article_id,
        article_code=article_code,
        reasons=[reason],
    )

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return [explanation]

    monkeypatch.setattr(
        planning_health,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        planning_health,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/health-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "items" in body
    items = body["items"]
    assert len(items) == 1

    item = items[0]
    assert item["article_id"] == article_id
    assert item["article_code"] == article_code
    assert item["worst_risk_level"] == "warning"
    assert item["days_of_cover"] == pytest.approx(20.0)
    assert item["total_final_order_qty"] == 30
    assert item["dominant_limiting_constraint"] == "strictness"


def test_health_portfolio_worst_risk_and_flags(client, db_session, monkeypatch):
    article_id = 2
    article_code = "ART-RISK"

    entries = [
        ArticleBundleRiskEntry(
            article_id=article_id,
            article_code=article_code,
            bundle_type_id=1,
            bundle_type_name="BT-OK",
            avg_daily_sales=1.0,
            total_available_bundles=10,
            days_of_cover=10.0,
            risk_level=BundleRiskLevel.OK,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="ok",
        ),
        ArticleBundleRiskEntry(
            article_id=article_id,
            article_code=article_code,
            bundle_type_id=2,
            bundle_type_name="BT-WARN",
            avg_daily_sales=1.0,
            total_available_bundles=5,
            days_of_cover=5.0,
            risk_level=BundleRiskLevel.WARNING,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="warn",
        ),
        ArticleBundleRiskEntry(
            article_id=article_id,
            article_code=article_code,
            bundle_type_id=3,
            bundle_type_name="BT-CRIT",
            avg_daily_sales=1.0,
            total_available_bundles=3,
            days_of_cover=3.0,
            risk_level=BundleRiskLevel.CRITICAL,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="crit",
        ),
    ]

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return entries

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        explanation = ArticleOrderExplanation(
            article_id=article_id,
            article_code=article_code,
            reasons=[],
        )
        return [explanation]

    monkeypatch.setattr(
        planning_health,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        planning_health,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/health-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 1
    item = items[0]

    assert item["worst_risk_level"] == "critical"
    assert item["has_critical"] is True
    assert item["has_warning"] is True
    assert item["days_of_cover"] == pytest.approx(3.0)


def test_health_portfolio_dominant_limiting_constraint(client, db_session, monkeypatch):
    article_id = 3
    article_code = "ART-CONSTR"

    risk_entry = ArticleBundleRiskEntry(
        article_id=article_id,
        article_code=article_code,
        bundle_type_id=1,
        bundle_type_name="BT-1",
        avg_daily_sales=1.0,
        total_available_bundles=10,
        days_of_cover=10.0,
        risk_level=BundleRiskLevel.OK,
        safety_stock_days=7,
        alert_threshold_days=14,
        overstock_threshold_days=42,
        explanation="ok",
    )

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return [risk_entry]

    reasons = [
        OrderProposalReason(
            article_id=article_id,
            article_code=article_code,
            color_id=None,
            color_name=None,
            elastic_type_id=None,
            elastic_type_name=None,
            proposed_qty=0,
            base_deficit=0,
            strictness=1.0,
            adjusted_deficit=0.0,
            min_fabric_batch=None,
            min_elastic_batch=None,
            color_min_batch=None,
            total_available_before=0,
            forecast_horizon_days=None,
            final_order_qty=10,
            limiting_constraint="fabric_min_batch",
            explanation="",
        ),
        OrderProposalReason(
            article_id=article_id,
            article_code=article_code,
            color_id=None,
            color_name=None,
            elastic_type_id=None,
            elastic_type_name=None,
            proposed_qty=0,
            base_deficit=0,
            strictness=1.0,
            adjusted_deficit=0.0,
            min_fabric_batch=None,
            min_elastic_batch=None,
            color_min_batch=None,
            total_available_before=0,
            forecast_horizon_days=None,
            final_order_qty=5,
            limiting_constraint="fabric_min_batch",
            explanation="",
        ),
        OrderProposalReason(
            article_id=article_id,
            article_code=article_code,
            color_id=None,
            color_name=None,
            elastic_type_id=None,
            elastic_type_name=None,
            proposed_qty=0,
            base_deficit=0,
            strictness=1.0,
            adjusted_deficit=0.0,
            min_fabric_batch=None,
            min_elastic_batch=None,
            color_min_batch=None,
            total_available_before=0,
            forecast_horizon_days=None,
            final_order_qty=3,
            limiting_constraint="none",
            explanation="",
        ),
        OrderProposalReason(
            article_id=article_id,
            article_code=article_code,
            color_id=None,
            color_name=None,
            elastic_type_id=None,
            elastic_type_name=None,
            proposed_qty=0,
            base_deficit=0,
            strictness=1.0,
            adjusted_deficit=0.0,
            min_fabric_batch=None,
            min_elastic_batch=None,
            color_min_batch=None,
            total_available_before=0,
            forecast_horizon_days=None,
            final_order_qty=2,
            limiting_constraint="elastic_min_batch",
            explanation="",
        ),
    ]

    explanation = ArticleOrderExplanation(
        article_id=article_id,
        article_code=article_code,
        reasons=reasons,
    )

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return [explanation]

    monkeypatch.setattr(
        planning_health,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        planning_health,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/health-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 1
    item = items[0]

    assert item["total_final_order_qty"] == 20
    assert item["dominant_limiting_constraint"] == "fabric_min_batch"


def test_health_portfolio_filters_article_ids_and_is_active(client, db_session, monkeypatch):
    active_id = 10
    inactive_id = 20

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        results: list[ArticleBundleRiskEntry] = []
        if article_ids is None:
            ids = [active_id]
        else:
            ids = [aid for aid in article_ids if aid in (active_id, inactive_id)]
        for aid in ids:
            results.append(
                ArticleBundleRiskEntry(
                    article_id=aid,
                    article_code=f"ART-{aid}",
                    bundle_type_id=1,
                    bundle_type_name="BT",
                    avg_daily_sales=1.0,
                    total_available_bundles=10,
                    days_of_cover=10.0,
                    risk_level=BundleRiskLevel.OK,
                    safety_stock_days=7,
                    alert_threshold_days=14,
                    overstock_threshold_days=42,
                    explanation="",
                )
            )
        return results

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        results: list[ArticleOrderExplanation] = []
        if article_ids is None:
            ids = [active_id]
        else:
            ids = [aid for aid in article_ids if aid in (active_id, inactive_id)]
        for aid in ids:
            reason = OrderProposalReason(
                article_id=aid,
                article_code=f"ART-{aid}",
                color_id=None,
                color_name=None,
                elastic_type_id=None,
                elastic_type_name=None,
                proposed_qty=0,
                base_deficit=0,
                strictness=1.0,
                adjusted_deficit=0.0,
                min_fabric_batch=None,
                min_elastic_batch=None,
                color_min_batch=None,
                total_available_before=0,
                forecast_horizon_days=None,
                final_order_qty=5,
                limiting_constraint="none",
                explanation="",
            )
            results.append(
                ArticleOrderExplanation(
                    article_id=aid,
                    article_code=f"ART-{aid}",
                    reasons=[reason],
                )
            )
        return results

    monkeypatch.setattr(
        planning_health,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        planning_health,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp_all = client.get("/api/v1/planning/health-portfolio")
    assert resp_all.status_code == 200, resp_all.text
    items_all = resp_all.json()["items"]
    ids_all = {it["article_id"] for it in items_all}
    assert active_id in ids_all
    assert inactive_id not in ids_all

    resp_filtered = client.get(
        "/api/v1/planning/health-portfolio",
        params={"article_ids": [inactive_id]},
    )
    assert resp_filtered.status_code == 200, resp_filtered.text
    items_filtered = resp_filtered.json()["items"]
    ids_filtered = {it["article_id"] for it in items_filtered}
    assert ids_filtered == {inactive_id}


def test_health_portfolio_empty_result_when_no_active(client, db_session, monkeypatch):
    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        planning_health,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        planning_health,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/health-portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["items"] == []
