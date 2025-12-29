from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import MonitoringAlertRule


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


def test_create_alert_rule_valid(client, db_session):
    payload = {
        "name": "Too many critical",
        "metric": "risk_critical",
        "threshold_type": "above",
        "threshold_value": 0,
        "severity": "critical",
        "is_active": True,
    }

    resp = client.post("/api/v1/planning/monitoring/alert-rules", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["id"] is not None
    assert data["name"] == payload["name"]
    assert data["metric"] == payload["metric"]
    assert data["threshold_type"] == payload["threshold_type"]
    assert data["threshold_value"] == payload["threshold_value"]
    assert data["severity"] == payload["severity"]
    assert data["is_active"] is True

    rule_id = data["id"]
    rule = (
        db_session.query(MonitoringAlertRule)
        .filter(MonitoringAlertRule.id == rule_id)
        .first()
    )
    assert rule is not None
    assert rule.name == payload["name"]
    assert rule.metric == payload["metric"]
    assert rule.threshold_type == payload["threshold_type"]
    assert rule.threshold_value == payload["threshold_value"]
    assert rule.severity == payload["severity"]
    assert rule.is_active is True

    resp_list = client.get("/api/v1/planning/monitoring/alert-rules")
    assert resp_list.status_code == 200, resp_list.text
    body = resp_list.json()
    items = body["items"]
    ids = {item["id"] for item in items}
    assert rule_id in ids


def test_create_alert_rule_rejects_invalid_values(client, db_session):  # noqa: ARG001
    base_payload = {
        "name": "Invalid rule",
        "metric": "risk_critical",
        "threshold_type": "above",
        "threshold_value": 0,
        "severity": "critical",
        "is_active": True,
    }

    payload = dict(base_payload)
    payload["metric"] = "something_weird"
    resp = client.post("/api/v1/planning/monitoring/alert-rules", json=payload)
    assert resp.status_code == 422

    payload = dict(base_payload)
    payload["threshold_type"] = "x"
    resp = client.post("/api/v1/planning/monitoring/alert-rules", json=payload)
    assert resp.status_code == 422

    payload = dict(base_payload)
    payload["severity"] = "error"
    resp = client.post("/api/v1/planning/monitoring/alert-rules", json=payload)
    assert resp.status_code == 422

    payload = dict(base_payload)
    payload["threshold_value"] = -1
    resp = client.post("/api/v1/planning/monitoring/alert-rules", json=payload)
    assert resp.status_code == 422


def test_update_alert_rule(client, db_session):
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

    payload = {
        "threshold_value": 10,
        "is_active": False,
    }

    resp = client.patch(
        f"/api/v1/planning/monitoring/alert-rules/{rule.id}",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["id"] == rule.id
    assert data["threshold_value"] == 10
    assert data["is_active"] is False

    db_session.refresh(rule)
    assert rule.threshold_value == 10
    assert rule.is_active is False


def test_delete_alert_rule_and_404(client, db_session):
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

    resp = client.delete(
        f"/api/v1/planning/monitoring/alert-rules/{rule.id}",
    )
    assert resp.status_code == 204, resp.text

    exists = (
        db_session.query(MonitoringAlertRule)
        .filter(MonitoringAlertRule.id == rule.id)
        .first()
    )
    assert exists is None

    resp_patch = client.patch(
        f"/api/v1/planning/monitoring/alert-rules/{rule.id}",
        json={"threshold_value": 5},
    )
    assert resp_patch.status_code == 404

    resp_delete = client.delete(
        f"/api/v1/planning/monitoring/alert-rules/{rule.id}",
    )
    assert resp_delete.status_code == 404
