from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import Size


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


def test_get_size_returns_structured_404(client):
    response = client.get("/api/v1/size/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "size_not_found",
        "message": "Size not found",
        "size_id": 999999,
        "next_steps": ["use_existing_size_id"],
    }


def test_create_size_returns_structured_409_for_duplicate_label(client, db_session):
    db_session.add(Size(label="XL", sort_order=1))
    db_session.commit()

    response = client.post(
        "/api/v1/size/",
        json={"label": "XL", "sort_order": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "size_label_already_exists",
        "message": "Size label already exists",
        "field": "label",
        "size_label": "XL",
        "next_steps": ["use_unique_size_label"],
    }


def test_patch_size_returns_structured_409_for_duplicate_label(client, db_session):
    existing = Size(label="S", sort_order=1)
    target = Size(label="M", sort_order=2)
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/size/{target.id}",
        json={"label": "S"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "size_label_already_exists",
        "message": "Size label already exists",
        "field": "label",
        "size_label": "S",
        "next_steps": ["use_unique_size_label"],
    }
