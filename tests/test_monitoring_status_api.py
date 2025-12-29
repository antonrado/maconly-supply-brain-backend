from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
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


def test_monitoring_status_critical_alerts_dominate(client, db_session, monkeypatch):  # noqa: ARG001
    fixed_datetime = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    alerts = [
        ActiveAlertSchema(
            rule_id=1,
            name="Critical 1",
            severity="critical",
            metric="risk_critical",
            current_value=5,
            threshold_type="above",
            threshold_value=0,
        ),
        ActiveAlertSchema(
            rule_id=2,
            name="Warning 1",
            severity="warning",
            metric="risk_warning",
            current_value=10,
            threshold_type="above",
            threshold_value=5,
        ),
    ]

    def fake_evaluate_active_alerts(db):  # noqa: ARG001
        return alerts

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return MonitoringSnapshot(
            integrations=IntegrationStatus(
                wb_accounts_total=1,
                wb_accounts_active=1,
                ms_accounts_total=1,
                ms_accounts_active=1,
            ),
            risks=RiskSummary(
                critical=0,
                warning=0,
                ok=1,
                overstock=0,
                no_data=0,
            ),
            orders=OrderSummary(
                articles_with_orders=0,
                total_final_order_qty=0,
            ),
            updated_at=fixed_datetime,
        )

    monkeypatch.setattr(
        monitoring_status,
        "evaluate_active_alerts",
        fake_evaluate_active_alerts,
    )
    monkeypatch.setattr(
        monitoring_status,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp_status = client.get("/api/v1/planning/monitoring/status")
    assert resp_status.status_code == 200, resp_status.text
    body_status = resp_status.json()

    assert body_status["overall_status"] == "critical"
    assert body_status["critical_alerts"] == 1
    assert body_status["warning_alerts"] == 1
    assert body_status["updated_at"] == fixed_datetime.isoformat()

    resp_boot = client.get("/api/v1/planning/monitoring/bootstrap")
    assert resp_boot.status_code == 200, resp_boot.text
    body_boot = resp_boot.json()["status"]

    assert body_boot["overall_status"] == "critical"
    assert body_boot["critical_alerts"] == 1
    assert body_boot["warning_alerts"] == 1


def test_monitoring_status_warning_from_snapshot_without_alerts(client, db_session, monkeypatch):  # noqa: ARG001
    fixed_datetime = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def fake_evaluate_active_alerts(db):  # noqa: ARG001
        return []

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return MonitoringSnapshot(
            integrations=IntegrationStatus(
                wb_accounts_total=1,
                wb_accounts_active=0,
                ms_accounts_total=1,
                ms_accounts_active=1,
            ),
            risks=RiskSummary(
                critical=5,
                warning=0,
                ok=0,
                overstock=0,
                no_data=0,
            ),
            orders=OrderSummary(
                articles_with_orders=0,
                total_final_order_qty=0,
            ),
            updated_at=fixed_datetime,
        )

    monkeypatch.setattr(
        monitoring_status,
        "evaluate_active_alerts",
        fake_evaluate_active_alerts,
    )
    monkeypatch.setattr(
        monitoring_status,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.get("/api/v1/planning/monitoring/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["overall_status"] == "warning"
    assert body["critical_alerts"] == 0
    assert body["warning_alerts"] == 0
    assert body["updated_at"] == fixed_datetime.isoformat()


def test_monitoring_status_ok_when_clean_snapshot_and_no_alerts(client, db_session, monkeypatch):  # noqa: ARG001
    fixed_datetime = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def fake_evaluate_active_alerts(db):  # noqa: ARG001
        return []

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return MonitoringSnapshot(
            integrations=IntegrationStatus(
                wb_accounts_total=2,
                wb_accounts_active=2,
                ms_accounts_total=1,
                ms_accounts_active=1,
            ),
            risks=RiskSummary(
                critical=0,
                warning=0,
                ok=10,
                overstock=0,
                no_data=0,
            ),
            orders=OrderSummary(
                articles_with_orders=0,
                total_final_order_qty=0,
            ),
            updated_at=fixed_datetime,
        )

    monkeypatch.setattr(
        monitoring_status,
        "evaluate_active_alerts",
        fake_evaluate_active_alerts,
    )
    monkeypatch.setattr(
        monitoring_status,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp_status = client.get("/api/v1/planning/monitoring/status")
    assert resp_status.status_code == 200, resp_status.text
    body_status = resp_status.json()

    assert body_status["overall_status"] == "ok"
    assert body_status["critical_alerts"] == 0
    assert body_status["warning_alerts"] == 0
    assert body_status["updated_at"] == fixed_datetime.isoformat()

    resp_boot = client.get("/api/v1/planning/monitoring/bootstrap")
    assert resp_boot.status_code == 200, resp_boot.text
    body_boot = resp_boot.json()["status"]

    assert body_boot["overall_status"] == "ok"
    assert body_boot["critical_alerts"] == 0
    assert body_boot["warning_alerts"] == 0
