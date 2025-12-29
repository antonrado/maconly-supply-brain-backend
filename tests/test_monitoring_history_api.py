from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import MonitoringSnapshotRecord
from app.schemas.monitoring import IntegrationStatus, MonitoringSnapshot, OrderSummary, RiskSummary
from app.services import monitoring_history


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


def test_capture_monitoring_snapshot_persists_record(client, db_session, monkeypatch):
    snapshot = MonitoringSnapshot(
        integrations=IntegrationStatus(
            wb_accounts_total=2,
            wb_accounts_active=1,
            ms_accounts_total=1,
            ms_accounts_active=1,
        ),
        risks=RiskSummary(
            critical=3,
            warning=4,
            ok=5,
            overstock=6,
            no_data=7,
        ),
        orders=OrderSummary(
            articles_with_orders=2,
            total_final_order_qty=42,
        ),
        updated_at=datetime.now(timezone.utc),
    )

    def fake_build_monitoring_snapshot(db):  # noqa: ARG001
        return snapshot

    monkeypatch.setattr(
        monitoring_history,
        "build_monitoring_snapshot",
        fake_build_monitoring_snapshot,
    )

    resp = client.post("/api/v1/planning/monitoring/snapshot/capture")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert isinstance(body["id"], int) and body["id"] > 0

    assert body["wb_accounts_total"] == snapshot.integrations.wb_accounts_total
    assert body["wb_accounts_active"] == snapshot.integrations.wb_accounts_active
    assert body["ms_accounts_total"] == snapshot.integrations.ms_accounts_total
    assert body["ms_accounts_active"] == snapshot.integrations.ms_accounts_active

    assert body["risk_critical"] == snapshot.risks.critical
    assert body["risk_warning"] == snapshot.risks.warning
    assert body["risk_ok"] == snapshot.risks.ok
    assert body["risk_overstock"] == snapshot.risks.overstock
    assert body["risk_no_data"] == snapshot.risks.no_data

    assert body["articles_with_orders"] == snapshot.orders.articles_with_orders
    assert body["total_final_order_qty"] == snapshot.orders.total_final_order_qty

    # Check that record is actually in DB
    records = db_session.query(MonitoringSnapshotRecord).all()
    assert len(records) == 1
    rec = records[0]
    assert rec.wb_accounts_total == snapshot.integrations.wb_accounts_total
    assert rec.risk_critical == snapshot.risks.critical
    assert rec.total_final_order_qty == snapshot.orders.total_final_order_qty


def test_get_monitoring_history_empty(client, db_session):  # noqa: ARG001
    resp = client.get("/api/v1/planning/monitoring/history")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": []}


def test_get_monitoring_history_with_limit_and_ordering(client, db_session):
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    rec1 = MonitoringSnapshotRecord(
        created_at=base_time,
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
        created_at=base_time + timedelta(days=1),
        wb_accounts_total=1,
        wb_accounts_active=1,
        ms_accounts_total=1,
        ms_accounts_active=1,
        risk_critical=2,
        risk_warning=0,
        risk_ok=0,
        risk_overstock=0,
        risk_no_data=0,
        articles_with_orders=1,
        total_final_order_qty=20,
    )
    rec3 = MonitoringSnapshotRecord(
        created_at=base_time + timedelta(days=2),
        wb_accounts_total=2,
        wb_accounts_active=2,
        ms_accounts_total=1,
        ms_accounts_active=1,
        risk_critical=3,
        risk_warning=0,
        risk_ok=0,
        risk_overstock=0,
        risk_no_data=0,
        articles_with_orders=2,
        total_final_order_qty=30,
    )

    db_session.add_all([rec1, rec2, rec3])
    db_session.commit()

    resp = client.get("/api/v1/planning/monitoring/history", params={"limit": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    items = body["items"]
    assert len(items) == 2

    # Should be ordered by created_at DESC, so rec3 then rec2
    assert items[0]["risk_critical"] == 3
    assert items[1]["risk_critical"] == 2


def test_get_monitoring_history_limit_validation(client, db_session):  # noqa: ARG001
    resp_low = client.get("/api/v1/planning/monitoring/history", params={"limit": 0})
    assert resp_low.status_code == 422

    resp_high = client.get("/api/v1/planning/monitoring/history", params={"limit": 9999})
    assert resp_high.status_code == 422
