from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import Color


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


def test_get_color_returns_structured_404(client):
    response = client.get("/api/v1/color/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "color_not_found",
        "message": "Color not found",
        "color_id": 999999,
        "field": "color_id",
        "field_metadata": {
            "description": "Requested color identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_color_id"],
    }


def test_create_color_returns_structured_409_for_duplicate_inner_code(client, db_session):
    db_session.add(Color(inner_code="BLK", description="Black", pantone_code=None))
    db_session.commit()

    response = client.post(
        "/api/v1/color/",
        json={"inner_code": "BLK", "description": "Duplicate", "pantone_code": None},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "color_inner_code_already_exists",
        "message": "Color inner_code already exists",
        "field": "inner_code",
        "field_metadata": {
            "description": "Requested color inner_code",
            "type": "string",
        },
        "inner_code": "BLK",
        "next_steps": ["use_unique_color_inner_code"],
    }


def test_patch_color_returns_structured_409_for_duplicate_inner_code(client, db_session):
    existing = Color(inner_code="BLK", description="Black", pantone_code=None)
    target = Color(inner_code="WHT", description="White", pantone_code=None)
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/color/{target.id}",
        json={"inner_code": "BLK"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "color_inner_code_already_exists",
        "message": "Color inner_code already exists",
        "field": "inner_code",
        "field_metadata": {
            "description": "Requested color inner_code",
            "type": "string",
        },
        "inner_code": "BLK",
        "next_steps": ["use_unique_color_inner_code"],
    }
