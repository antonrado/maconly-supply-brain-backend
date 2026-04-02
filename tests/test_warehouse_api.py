from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import Warehouse


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


def test_get_warehouse_returns_structured_404(client):
    response = client.get("/api/v1/warehouse/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "warehouse_not_found",
        "message": "Warehouse not found",
        "warehouse_id": 999999,
        "field": "warehouse_id",
        "field_metadata": {
            "description": "Requested warehouse identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_warehouse_id"],
    }


def test_create_warehouse_returns_structured_409_for_duplicate_code(client, db_session):
    db_session.add(Warehouse(code="NSK", name="Novosibirsk", type="internal"))
    db_session.commit()

    response = client.post(
        "/api/v1/warehouse/",
        json={"code": "NSK", "name": "Duplicate", "type": "internal"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "warehouse_code_already_exists",
        "message": "Warehouse code already exists",
        "field": "code",
        "field_metadata": {
            "description": "Requested warehouse code",
            "type": "string",
        },
        "warehouse_code": "NSK",
        "next_steps": ["use_unique_warehouse_code"],
    }


def test_patch_warehouse_returns_structured_409_for_duplicate_code(client, db_session):
    existing = Warehouse(code="MSK", name="Moscow", type="internal")
    target = Warehouse(code="SPB", name="Saint Petersburg", type="internal")
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/warehouse/{target.id}",
        json={"code": "MSK"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "warehouse_code_already_exists",
        "message": "Warehouse code already exists",
        "field": "code",
        "field_metadata": {
            "description": "Requested warehouse code",
            "type": "string",
        },
        "warehouse_code": "MSK",
        "next_steps": ["use_unique_warehouse_code"],
    }
