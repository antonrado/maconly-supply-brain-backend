from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import BundleType


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


def test_get_bundle_type_returns_structured_404(client):
    response = client.get("/api/v1/bundle-type/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "bundle_type_not_found",
        "message": "BundleType not found",
        "bundle_type_id": 999999,
        "field": "bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_bundle_type_id"],
    }


def test_create_bundle_type_returns_structured_409_for_duplicate_code(client, db_session):
    db_session.add(BundleType(code="SET", name="Set"))
    db_session.commit()

    response = client.post(
        "/api/v1/bundle-type/",
        json={"code": "SET", "name": "Duplicate"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bundle_type_code_already_exists",
        "message": "BundleType code already exists",
        "field": "code",
        "field_metadata": {
            "description": "Requested bundle type code",
            "type": "string",
        },
        "bundle_type_code": "SET",
        "next_steps": ["use_unique_bundle_type_code"],
    }


def test_patch_bundle_type_returns_structured_409_for_duplicate_code(client, db_session):
    existing = BundleType(code="SET", name="Set")
    target = BundleType(code="BOX", name="Box")
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/bundle-type/{target.id}",
        json={"code": "SET"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bundle_type_code_already_exists",
        "message": "BundleType code already exists",
        "field": "code",
        "field_metadata": {
            "description": "Requested bundle type code",
            "type": "string",
        },
        "bundle_type_code": "SET",
        "next_steps": ["use_unique_bundle_type_code"],
    }
