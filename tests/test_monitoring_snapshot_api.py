from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import WbIntegrationAccount, MoySkladIntegrationAccount
from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.schemas.integrations import (
    IntegrationsConfigSnapshot,
    MoySkladAccountInfo,
    WbAccountInfo,
)
from app.schemas.order_explanation import ArticleOrderExplanation, OrderProposalReason
from app.services import monitoring


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


def test_monitoring_snapshot_empty_system(client, db_session, monkeypatch):  # noqa: ARG001
    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_integrations_config_snapshot(db):  # noqa: ARG001
        return IntegrationsConfigSnapshot(wb_accounts=[], moysklad_accounts=[])

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        monitoring,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_integrations_config_snapshot",
        fake_build_integrations_config_snapshot,
    )
    monkeypatch.setattr(
        monitoring,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/monitoring/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    integrations = body["integrations"]
    assert integrations["wb_accounts_total"] == 0
    assert integrations["wb_accounts_active"] == 0
    assert integrations["ms_accounts_total"] == 0
    assert integrations["ms_accounts_active"] == 0

    risks = body["risks"]
    assert risks == {
        "critical": 0,
        "warning": 0,
        "ok": 0,
        "overstock": 0,
        "no_data": 0,
    }

    orders = body["orders"]
    assert orders["articles_with_orders"] == 0
    assert orders["total_final_order_qty"] == 0

    assert "updated_at" in body
    # ISO-8601 parse check
    parsed = datetime.fromisoformat(body["updated_at"])
    assert isinstance(parsed, datetime)


def test_monitoring_snapshot_integrations_status(client, db_session, monkeypatch):
    wb1 = WbIntegrationAccount(
        name="WB-1",
        supplier_id="SUP-1",
        api_token="token-1",
        is_active=True,
    )
    wb2 = WbIntegrationAccount(
        name="WB-2",
        supplier_id=None,
        api_token="token-2",
        is_active=False,
    )
    ms1 = MoySkladIntegrationAccount(
        name="MS-1",
        account_id="ACC-1",
        api_token="token-3",
        is_active=True,
    )

    db_session.add_all([wb1, wb2, ms1])
    db_session.flush()

    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        monitoring,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/monitoring/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    integrations = body["integrations"]
    assert integrations["wb_accounts_total"] == 2
    assert integrations["wb_accounts_active"] == 1
    assert integrations["ms_accounts_total"] == 1
    assert integrations["ms_accounts_active"] == 1


def test_monitoring_snapshot_risk_summary(client, db_session, monkeypatch):  # noqa: ARG001
    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_integrations_config_snapshot(db):  # noqa: ARG001
        return IntegrationsConfigSnapshot(wb_accounts=[], moysklad_accounts=[])

    entries = [
        ArticleBundleRiskEntry(
            article_id=1,
            article_code="A1",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=1.0,
            total_available_bundles=10,
            days_of_cover=5.0,
            risk_level=BundleRiskLevel.CRITICAL,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="crit",
        ),
        ArticleBundleRiskEntry(
            article_id=2,
            article_code="A2",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=1.0,
            total_available_bundles=10,
            days_of_cover=8.0,
            risk_level=BundleRiskLevel.CRITICAL,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="crit2",
        ),
        ArticleBundleRiskEntry(
            article_id=3,
            article_code="A3",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=1.0,
            total_available_bundles=10,
            days_of_cover=10.0,
            risk_level=BundleRiskLevel.WARNING,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="warn",
        ),
        ArticleBundleRiskEntry(
            article_id=4,
            article_code="A4",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=1.0,
            total_available_bundles=10,
            days_of_cover=20.0,
            risk_level=BundleRiskLevel.OK,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="ok",
        ),
        ArticleBundleRiskEntry(
            article_id=5,
            article_code="A5",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=0.0,
            total_available_bundles=50,
            days_of_cover=None,
            risk_level=BundleRiskLevel.OVERSTOCK,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="over",
        ),
        ArticleBundleRiskEntry(
            article_id=6,
            article_code="A6",
            bundle_type_id=1,
            bundle_type_name="BT1",
            avg_daily_sales=0.0,
            total_available_bundles=0,
            days_of_cover=None,
            risk_level=BundleRiskLevel.NO_DATA,
            safety_stock_days=7,
            alert_threshold_days=14,
            overstock_threshold_days=42,
            explanation="nodata",
        ),
    ]

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return entries

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        monitoring,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_integrations_config_snapshot",
        fake_build_integrations_config_snapshot,
    )
    monkeypatch.setattr(
        monitoring,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/monitoring/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    risks = body["risks"]
    assert risks["critical"] == 2
    assert risks["warning"] == 1
    assert risks["ok"] == 1
    assert risks["overstock"] == 1
    assert risks["no_data"] == 1


def test_monitoring_snapshot_order_summary(client, db_session, monkeypatch):  # noqa: ARG001
    def fake_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_integrations_config_snapshot(db):  # noqa: ARG001
        return IntegrationsConfigSnapshot(wb_accounts=[], moysklad_accounts=[])

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    explanations = [
        ArticleOrderExplanation(
            article_id=1,
            article_code="A1",
            reasons=[
                OrderProposalReason(
                    article_id=1,
                    article_code="A1",
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
                    limiting_constraint="none",
                    explanation="",
                )
            ],
        ),
        ArticleOrderExplanation(
            article_id=2,
            article_code="A2",
            reasons=[
                OrderProposalReason(
                    article_id=2,
                    article_code="A2",
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
                    final_order_qty=0,
                    limiting_constraint="none",
                    explanation="",
                )
            ],
        ),
        ArticleOrderExplanation(
            article_id=3,
            article_code="A3",
            reasons=[
                OrderProposalReason(
                    article_id=3,
                    article_code="A3",
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
            ],
        ),
    ]

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return explanations

    monkeypatch.setattr(
        monitoring,
        "build_planning_health_portfolio",
        fake_build_planning_health_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_integrations_config_snapshot",
        fake_build_integrations_config_snapshot,
    )
    monkeypatch.setattr(
        monitoring,
        "build_bundle_risk_portfolio",
        fake_build_bundle_risk_portfolio,
    )
    monkeypatch.setattr(
        monitoring,
        "build_order_explanation_portfolio",
        fake_build_order_explanation_portfolio,
    )

    resp = client.get("/api/v1/planning/monitoring/snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    orders = body["orders"]
    assert orders["articles_with_orders"] == 2
    assert orders["total_final_order_qty"] == 15
