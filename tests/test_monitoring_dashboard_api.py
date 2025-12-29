from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.api.v1.endpoints import planning as planning_module
from app.models.models import MonitoringAlertRule, MonitoringSnapshotRecord
from app.schemas.monitoring import IntegrationStatus, MonitoringSnapshot, OrderSummary, RiskSummary
from app.schemas.monitoring_alerts import ActiveAlertSchema
from app.services import monitoring_status


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


def test_monitoring_dashboard_empty_db(client, db_session, monkeypatch):  # noqa: ARG001
    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=0,
            wb_accounts_active=0,
            ms_accounts_total=0,
            ms_accounts_active=0,
        ),
        risks=RiskSummary(
            critical=0,
            warning=0,
            ok=0,
            overstock=0,
            no_data=0,
        ),
        orders=OrderSummary(
            articles_with_orders=0,
            total_final_order_qty=0,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    monkeypatch.setattr(
        planning_module,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    snap = body["snapshot"]
    assert snap["integrations"]["wb_accounts_total"] == 0
    assert snap["risks"]["critical"] == 0
    assert snap["orders"]["total_final_order_qty"] == 0

    assert body["history"]["items"] == []
    assert body["alerts"]["items"] == []
    assert body["rules"]["items"] == []

    status = body["status"]
    assert status["overall_status"] == "warning"
    assert status["critical_alerts"] == 0
    assert status["warning_alerts"] == 0


def test_monitoring_dashboard_with_history_and_rules(client, db_session, monkeypatch):
    rec1 = MonitoringSnapshotRecord(
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        wb_accounts_total=1,
        wb_accounts_active=1,
        ms_accounts_total=0,
        ms_accounts_active=0,
        risk_critical=1,
        risk_warning=0,
        risk_ok=0,
        risk_overstock=0,
        risk_no_data=0,
        articles_with_orders=1,
        total_final_order_qty=10,
    )
    rec2 = MonitoringSnapshotRecord(
        created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        wb_accounts_total=2,
        wb_accounts_active=2,
        ms_accounts_total=1,
        ms_accounts_active=1,
        risk_critical=2,
        risk_warning=0,
        risk_ok=0,
        risk_overstock=0,
        risk_no_data=0,
        articles_with_orders=2,
        total_final_order_qty=20,
    )
    db_session.add_all([rec1, rec2])

    rule1 = MonitoringAlertRule(
        name="Rule 1",
        metric="risk_critical",
        threshold_type="above",
        threshold_value=0,
        severity="critical",
        is_active=True,
    )
    rule2 = MonitoringAlertRule(
        name="Rule 2",
        metric="risk_warning",
        threshold_type="above",
        threshold_value=5,
        severity="warning",
        is_active=True,
    )
    db_session.add_all([rule1, rule2])
    db_session.commit()

    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=5,
            wb_accounts_active=5,
            ms_accounts_total=5,
            ms_accounts_active=5,
        ),
        risks=RiskSummary(
            critical=999,
            warning=0,
            ok=0,
            overstock=0,
            no_data=0,
        ),
        orders=OrderSummary(
            articles_with_orders=0,
            total_final_order_qty=0,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    monkeypatch.setattr(
        planning_module,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    snap = body["snapshot"]
    assert snap["risks"]["critical"] == 999

    history_items = body["history"]["items"]
    assert len(history_items) == 2

    rules_items = body["rules"]["items"]
    assert len(rules_items) == 2
    rule_ids = {r["id"] for r in rules_items}
    assert rule_ids == {rule1.id, rule2.id}

    assert isinstance(body["alerts"]["items"], list)


def test_monitoring_dashboard_alerts_triggered(client, db_session, monkeypatch):
    rec = MonitoringSnapshotRecord(
        created_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        wb_accounts_total=0,
        wb_accounts_active=0,
        ms_accounts_total=0,
        ms_accounts_active=0,
        risk_critical=5,
        risk_warning=0,
        risk_ok=0,
        risk_overstock=0,
        risk_no_data=0,
        articles_with_orders=0,
        total_final_order_qty=0,
    )
    db_session.add(rec)

    rule = MonitoringAlertRule(
        name="Too many critical",
        metric="risk_critical",
        threshold_type="above",
        threshold_value=0,
        severity="critical",
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()

    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=0,
            wb_accounts_active=0,
            ms_accounts_total=0,
            ms_accounts_active=0,
        ),
        risks=RiskSummary(
            critical=0,
            warning=0,
            ok=0,
            overstock=0,
            no_data=0,
        ),
        orders=OrderSummary(
            articles_with_orders=0,
            total_final_order_qty=0,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    monkeypatch.setattr(
        planning_module,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    alerts = body["alerts"]["items"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["metric"] == "risk_critical"
    assert alert["current_value"] == 5
    assert alert["rule_id"] == rule.id

    status = body["status"]
    assert status["overall_status"] == "critical"
    assert status["critical_alerts"] == 1
    assert status["warning_alerts"] == 0


def test_monitoring_dashboard_status_warning_only(client, db_session, monkeypatch):  # noqa: ARG001
    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=0,
            wb_accounts_active=0,
            ms_accounts_total=0,
            ms_accounts_active=0,
        ),
        risks=RiskSummary(
            critical=0,
            warning=0,
            ok=0,
            overstock=0,
            no_data=0,
        ),
        orders=OrderSummary(
            articles_with_orders=0,
            total_final_order_qty=0,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    warning_alerts = [
        ActiveAlertSchema(
            rule_id=1,
            name="Warning 1",
            severity="warning",
            metric="risk_warning",
            current_value=10,
            threshold_type="above",
            threshold_value=5,
        ),
        ActiveAlertSchema(
            rule_id=2,
            name="Warning 2",
            severity="warning",
            metric="risk_overstock",
            current_value=20,
            threshold_type="above",
            threshold_value=10,
        ),
    ]

    def fake_evaluate_active_alerts(db):  # noqa: ARG001
        return warning_alerts

    monkeypatch.setattr(
        planning_module,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )
    monkeypatch.setattr(
        planning_module,
        "evaluate_active_alerts",
        fake_evaluate_active_alerts,
    )
    monkeypatch.setattr(
        monitoring_status,
        "evaluate_active_alerts",
        fake_evaluate_active_alerts,
    )

    resp = client.get("/api/v1/planning/monitoring/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    alerts = body["alerts"]["items"]
    assert len(alerts) == 2

    status = body["status"]
    assert status["overall_status"] == "warning"
    assert status["critical_alerts"] == 0
    assert status["warning_alerts"] == 2
