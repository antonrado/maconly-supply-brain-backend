from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import MonitoringAlertRule, MonitoringSnapshotRecord
from app.schemas.monitoring import IntegrationStatus, MonitoringSnapshot, OrderSummary, RiskSummary
from app.services import monitoring_alerts


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


def test_monitoring_alerts_empty_rules(client, db_session, monkeypatch):  # noqa: ARG001
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
        monitoring_alerts,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": []}


def test_monitoring_alerts_triggered_and_not_triggered_rules(client, db_session, monkeypatch):
    rule1 = MonitoringAlertRule(
        name="Too many critical risks",
        metric="risk_critical",
        threshold_type="above",
        threshold_value=0,
        severity="critical",
        is_active=True,
    )
    rule2 = MonitoringAlertRule(
        name="No active WB accounts",
        metric="wb_accounts_active",
        threshold_type="below",
        threshold_value=1,
        severity="warning",
        is_active=True,
    )
    rule3 = MonitoringAlertRule(
        name="Too many warnings",
        metric="risk_warning",
        threshold_type="above",
        threshold_value=10,
        severity="warning",
        is_active=True,
    )
    db_session.add_all([rule1, rule2, rule3])
    db_session.commit()

    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=2,
            wb_accounts_active=0,
            ms_accounts_total=1,
            ms_accounts_active=1,
        ),
        risks=RiskSummary(
            critical=2,
            warning=3,
            ok=0,
            overstock=0,
            no_data=0,
        ),
        orders=OrderSummary(
            articles_with_orders=1,
            total_final_order_qty=100,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    monkeypatch.setattr(
        monitoring_alerts,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 2
    metrics = {a["metric"] for a in items}
    assert metrics == {"risk_critical", "wb_accounts_active"}

    crit_alert = next(a for a in items if a["metric"] == "risk_critical")
    assert crit_alert["current_value"] == 2
    assert crit_alert["rule_id"] == rule1.id

    wb_alert = next(a for a in items if a["metric"] == "wb_accounts_active")
    assert wb_alert["current_value"] == 0
    assert wb_alert["rule_id"] == rule2.id


def test_monitoring_alerts_history_has_priority_over_snapshot(client, db_session, monkeypatch):
    rule = MonitoringAlertRule(
        name="Critical risks from history",
        metric="risk_critical",
        threshold_type="above",
        threshold_value=0,
        severity="critical",
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()

    # History record with risk_critical=5
    db_session.add(
        MonitoringSnapshotRecord(
            created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
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
    )
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
        monitoring_alerts,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 1
    alert = items[0]
    assert alert["metric"] == "risk_critical"
    assert alert["current_value"] == 5


def test_monitoring_alerts_ignores_invalid_rules(client, db_session, monkeypatch):
    valid_rule = MonitoringAlertRule(
        name="Valid critical rule",
        metric="risk_critical",
        threshold_type="above",
        threshold_value=0,
        severity="critical",
        is_active=True,
    )
    bad_metric_rule = MonitoringAlertRule(
        name="Unknown metric",
        metric="unknown_metric",
        threshold_type="above",
        threshold_value=0,
        severity="warning",
        is_active=True,
    )
    bad_threshold_rule = MonitoringAlertRule(
        name="Weird threshold type",
        metric="risk_critical",
        threshold_type="weird",
        threshold_value=0,
        severity="warning",
        is_active=True,
    )

    db_session.add_all([valid_rule, bad_metric_rule, bad_threshold_rule])
    db_session.commit()

    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=0,
            wb_accounts_active=0,
            ms_accounts_total=0,
            ms_accounts_active=0,
        ),
        risks=RiskSummary(
            critical=3,
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
        monitoring_alerts,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/alerts")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 1
    alert = items[0]
    assert alert["rule_id"] == valid_rule.id
    assert alert["metric"] == "risk_critical"
    assert alert["current_value"] == 3
