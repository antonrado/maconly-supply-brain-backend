from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.schemas.integrations import IntegrationsConfigSnapshot
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


def test_monitoring_snapshot_does_not_build_planning_health_portfolio(
    client,
    db_session,
    monkeypatch,
):  # noqa: ARG001
    def fail_build_planning_health_portfolio(db, article_ids=None):  # noqa: ARG001
        raise AssertionError(
            "build_planning_health_portfolio should not be called by monitoring snapshot"
        )

    def fake_build_integrations_config_snapshot(db):  # noqa: ARG001
        return IntegrationsConfigSnapshot(wb_accounts=[], moysklad_accounts=[])

    def fake_build_bundle_risk_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    def fake_build_order_explanation_portfolio(db, article_ids=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(
        monitoring,
        "build_planning_health_portfolio",
        fail_build_planning_health_portfolio,
        raising=False,
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
    assert body["orders"] == {
        "articles_with_orders": 0,
        "total_final_order_qty": 0,
    }
