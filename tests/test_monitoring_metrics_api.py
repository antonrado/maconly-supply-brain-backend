from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.monitoring_timeseries import SUPPORTED_METRICS
from app.services.monitoring_alert_rules_seed import RULES
from app.services.monitoring_metrics import (
    build_monitoring_metrics_catalog,
    get_alert_rule_metrics,
    get_timeseries_metrics,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_monitoring_metrics_basic_happy_path(client):
    resp = client.get("/api/v1/planning/monitoring/metrics")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    items = body["items"]
    assert isinstance(items, list)
    assert len(items) > 0

    metrics = {item["metric"] for item in items}
    assert "risk_critical" in metrics
    assert "risk_warning" in metrics
    assert "wb_accounts_active" in metrics
    assert "total_final_order_qty" in metrics

    rc = next(item for item in items if item["metric"] == "risk_critical")
    assert rc["category"] == "risk"
    assert isinstance(rc["label"], str) and rc["label"]
    assert isinstance(rc["description"], str) and rc["description"]
    assert rc["supports_alerts"] is True
    assert rc["supports_timeseries"] is True
    assert rc["used_in_status"] is True


def test_monitoring_metrics_consistency_with_supported_timeseries_metrics(client):
    resp = client.get("/api/v1/planning/monitoring/metrics")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    items = body["items"]

    metrics_from_api = {item["metric"] for item in items if item["supports_timeseries"]}

    assert SUPPORTED_METRICS.issubset(metrics_from_api)


def test_monitoring_metrics_consistency_with_alert_rule_metrics(client):
    rule_metrics = {r["metric"] for r in RULES}

    resp = client.get("/api/v1/planning/monitoring/metrics")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    items = body["items"]

    metrics_with_alerts = {item["metric"] for item in items if item["supports_alerts"]}

    assert rule_metrics.issubset(metrics_with_alerts)


def test_timeseries_metrics_match_catalog():
    from_catalog = get_timeseries_metrics()
    from_service = SUPPORTED_METRICS

    assert from_service == from_catalog


def test_alert_rule_metrics_match_catalog():
    from_catalog = get_alert_rule_metrics()
    rule_metrics = {r["metric"] for r in RULES}

    assert rule_metrics.issubset(from_catalog)


def test_status_flags_consistent_with_alert_flags():
    catalog = build_monitoring_metrics_catalog()
    for item in catalog.items:
        if item.supports_alerts:
            assert item.used_in_status is True
