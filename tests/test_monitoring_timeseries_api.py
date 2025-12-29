from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import MonitoringSnapshotRecord


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


def test_monitoring_timeseries_basic_happy_path(client, db_session):
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    records = []
    for i in range(4):
        rec = MonitoringSnapshotRecord(
            created_at=base_time + timedelta(days=i),
            wb_accounts_total=0,
            wb_accounts_active=i,
            ms_accounts_total=0,
            ms_accounts_active=0,
            risk_critical=i,
            risk_warning=0,
            risk_ok=0,
            risk_overstock=0,
            risk_no_data=0,
            articles_with_orders=0,
            total_final_order_qty=0,
        )
        records.append(rec)

    db_session.add_all(records)
    db_session.commit()

    resp = client.get(
        "/api/v1/planning/monitoring/timeseries",
        params={"metrics": ["risk_critical", "wb_accounts_active"], "limit": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 2

    series_by_metric = {s["metric"]: s for s in items}
    assert set(series_by_metric.keys()) == {"risk_critical", "wb_accounts_active"}

    expected_timestamps = [
        (base_time + timedelta(days=i)).isoformat()
        for i in range(1, 4)
    ]

    risk_series = series_by_metric["risk_critical"]
    risk_points = risk_series["points"]
    assert len(risk_points) == 3
    assert [p["timestamp"] for p in risk_points] == expected_timestamps
    assert [p["value"] for p in risk_points] == [1, 2, 3]

    wb_series = series_by_metric["wb_accounts_active"]
    wb_points = wb_series["points"]
    assert len(wb_points) == 3
    assert [p["timestamp"] for p in wb_points] == expected_timestamps
    assert [p["value"] for p in wb_points] == [1, 2, 3]


def test_monitoring_timeseries_unknown_metrics(client, db_session):  # noqa: ARG001
    resp = client.get(
        "/api/v1/planning/monitoring/timeseries",
        params={"metrics": ["foo", "bar"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": []}


def test_monitoring_timeseries_empty_history(client, db_session):  # noqa: ARG001
    resp = client.get(
        "/api/v1/planning/monitoring/timeseries",
        params={"metrics": ["risk_critical"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": []}


def test_monitoring_timeseries_missing_metrics_param(client, db_session):  # noqa: ARG001
    resp = client.get("/api/v1/planning/monitoring/timeseries")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["detail"] == "metrics query parameter is required"
