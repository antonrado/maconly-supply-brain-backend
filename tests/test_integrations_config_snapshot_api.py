from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import WbIntegrationAccount, MoySkladIntegrationAccount


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


def test_integrations_config_snapshot_empty(client, db_session):
    resp = client.get("/api/v1/planning/integrations/config-snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body == {"wb_accounts": [], "moysklad_accounts": []}


def test_integrations_config_snapshot_multiple_accounts(client, db_session):
    wb1 = WbIntegrationAccount(
        name="WB Account 1",
        supplier_id="SUP-1",
        api_token="wb-token-1",
        is_active=True,
    )
    wb2 = WbIntegrationAccount(
        name="WB Account 2",
        supplier_id=None,
        api_token="wb-token-2",
        is_active=False,
    )
    ms1 = MoySkladIntegrationAccount(
        name="MS Account 1",
        account_id="ACC-1",
        api_token="ms-token-1",
        is_active=True,
    )

    db_session.add_all([wb1, wb2, ms1])
    db_session.flush()

    resp = client.get("/api/v1/planning/integrations/config-snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "wb_accounts" in body
    assert "moysklad_accounts" in body

    wb_accounts = body["wb_accounts"]
    ms_accounts = body["moysklad_accounts"]

    # All accounts should be present (active and inactive)
    wb_by_id = {row["id"]: row for row in wb_accounts}
    ms_by_id = {row["id"]: row for row in ms_accounts}

    assert {wb1.id, wb2.id} == set(wb_by_id.keys())
    assert {ms1.id} == set(ms_by_id.keys())

    wb1_json = wb_by_id[wb1.id]
    wb2_json = wb_by_id[wb2.id]
    ms1_json = ms_by_id[ms1.id]

    assert wb1_json["name"] == wb1.name
    assert wb1_json["supplier_id"] == wb1.supplier_id
    assert wb1_json["is_active"] is True

    assert wb2_json["name"] == wb2.name
    assert wb2_json["supplier_id"] is None
    assert wb2_json["is_active"] is False

    assert ms1_json["name"] == ms1.name
    assert ms1_json["account_id"] == ms1.account_id
    assert ms1_json["is_active"] is True


def test_integrations_config_snapshot_does_not_expose_tokens(client, db_session):
    wb_token = "super-secret-wb-token"
    ms_token = "super-secret-ms-token"

    wb = WbIntegrationAccount(
        name="WB Secure",
        supplier_id="SUP-SEC",
        api_token=wb_token,
        is_active=True,
    )
    ms = MoySkladIntegrationAccount(
        name="MS Secure",
        account_id="ACC-SEC",
        api_token=ms_token,
        is_active=True,
    )

    db_session.add_all([wb, ms])
    db_session.flush()

    resp = client.get("/api/v1/planning/integrations/config-snapshot")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Structure should always contain both keys
    assert "wb_accounts" in body
    assert "moysklad_accounts" in body

    # Field name api_token must not be present anywhere in the JSON
    text = resp.text
    assert "api_token" not in text

    # Token values must not appear under any fields
    assert wb_token not in text
    assert ms_token not in text
