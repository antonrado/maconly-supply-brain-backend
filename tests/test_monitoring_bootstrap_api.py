from __future__ import annotations

import inspect

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import app
from app.api.v1.endpoints import planning as planning_module
from app.services.monitoring_bootstrap import build_monitoring_bootstrap


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


def test_monitoring_bootstrap_status_aligned_with_status_endpoint(client):
    resp_boot = client.get("/api/v1/planning/monitoring/bootstrap")
    assert resp_boot.status_code == 200, resp_boot.text
    boot = resp_boot.json()

    resp_status = client.get("/api/v1/planning/monitoring/status")
    assert resp_status.status_code == 200, resp_status.text
    st = resp_status.json()

    assert "status" in boot
    status_boot = boot["status"]

    # Both responses must expose the same MonitoringStatusResponse fields
    for key in ("overall_status", "critical_alerts", "warning_alerts", "updated_at"):
        assert key in status_boot
        assert key in st

    # And the core status fields must match exactly
    assert status_boot["overall_status"] == st["overall_status"]
    assert status_boot["critical_alerts"] == st["critical_alerts"]
    assert status_boot["warning_alerts"] == st["warning_alerts"]

    # Basic shape checks for metrics and layout to keep regression coverage
    assert "metrics" in boot
    assert "layout" in boot

    metrics = boot["metrics"]
    assert isinstance(metrics["items"], list)
    assert len(metrics["items"]) > 0

    layout = boot["layout"]
    assert isinstance(layout["sections"], list)
    assert len(layout["sections"]) > 0


def test_monitoring_bootstrap_consistency_with_metrics_and_layout(client):
    # Bootstrap response
    resp_bootstrap = client.get("/api/v1/planning/monitoring/bootstrap")
    assert resp_bootstrap.status_code == 200, resp_bootstrap.text
    bootstrap = resp_bootstrap.json()

    # /monitoring/metrics
    resp_metrics = client.get("/api/v1/planning/monitoring/metrics")
    assert resp_metrics.status_code == 200, resp_metrics.text
    metrics_body = resp_metrics.json()

    # /monitoring/layout
    resp_layout = client.get("/api/v1/planning/monitoring/layout")
    assert resp_layout.status_code == 200, resp_layout.text
    layout_body = resp_layout.json()

    # Metrics: set of metric names must match exactly
    metrics_from_bootstrap = {m["metric"] for m in bootstrap["metrics"]["items"]}
    metrics_from_api = {m["metric"] for m in metrics_body["items"]}
    assert metrics_from_bootstrap == metrics_from_api

    # Layout: section IDs and tile IDs should match between bootstrap and /layout
    def _collect_ids(layout_json):
        section_ids = set()
        tile_ids = set()
        for section in layout_json["sections"]:
            section_ids.add(section["id"])
            for tile in section["tiles"]:
                tile_ids.add(tile["id"])
        return section_ids, tile_ids

    sections_bootstrap, tiles_bootstrap = _collect_ids(bootstrap["layout"])
    sections_layout, tiles_layout = _collect_ids(layout_body)

    assert sections_bootstrap == sections_layout
    assert tiles_bootstrap == tiles_layout


def test_monitoring_bootstrap_signatures_use_db():
    # API function must expose a db: Session dependency
    sig_api = inspect.signature(planning_module.get_monitoring_bootstrap)
    api_params = list(sig_api.parameters.values())
    assert len(api_params) == 1
    p = api_params[0]
    assert p.annotation is Session
    assert isinstance(p.default, Depends)
    assert p.default.dependency is get_db

    # Service function must also accept a db: Session argument
    sig_service = inspect.signature(build_monitoring_bootstrap)
    service_params = list(sig_service.parameters.values())
    assert len(service_params) == 1
    sp = service_params[0]
    assert sp.annotation is Session
