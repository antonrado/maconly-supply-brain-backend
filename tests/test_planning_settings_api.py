from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import PlanningSettings
from tests.test_utils import create_article


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


def test_get_planning_settings_returns_structured_404(client):
    response = client.get("/api/v1/planning-settings/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "planning_settings_not_found",
        "message": "PlanningSettings not found",
        "planning_settings_id": 999999,
        "field": "planning_settings_id",
        "field_metadata": {
            "description": "Requested planning settings identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_planning_settings_id"],
    }


def test_create_planning_settings_returns_structured_409_for_duplicate_article(client, db_session):
    article = create_article(db_session, code="PS-ART")
    db_session.add(
        PlanningSettings(
            article_id=article.id,
            is_active=True,
            min_fabric_batch=100,
            min_elastic_batch=50,
            alert_threshold_days=7,
            safety_stock_days=14,
            strictness=1.0,
            notes=None,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/planning-settings/",
        json={
            "article_id": article.id,
            "is_active": True,
            "min_fabric_batch": 100,
            "min_elastic_batch": 50,
            "alert_threshold_days": 7,
            "safety_stock_days": 14,
            "strictness": 1.0,
            "notes": None,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "planning_settings_article_already_exists",
        "message": "PlanningSettings for this article already exists",
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier for planning settings uniqueness",
            "type": "int",
        },
        "article_id": article.id,
        "next_steps": ["use_article_without_existing_planning_settings"],
    }


def test_patch_planning_settings_returns_structured_409_for_duplicate_article(client, db_session):
    article_one = create_article(db_session, code="PS-ART-1")
    article_two = create_article(db_session, code="PS-ART-2")

    existing = PlanningSettings(
        article_id=article_one.id,
        is_active=True,
        min_fabric_batch=100,
        min_elastic_batch=50,
        alert_threshold_days=7,
        safety_stock_days=14,
        strictness=1.0,
        notes=None,
    )
    target = PlanningSettings(
        article_id=article_two.id,
        is_active=True,
        min_fabric_batch=120,
        min_elastic_batch=60,
        alert_threshold_days=8,
        safety_stock_days=15,
        strictness=1.1,
        notes=None,
    )
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/planning-settings/{target.id}",
        json={"article_id": article_one.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "planning_settings_article_already_exists",
        "message": "PlanningSettings for this article already exists",
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier for planning settings uniqueness",
            "type": "int",
        },
        "article_id": article_one.id,
        "next_steps": ["use_article_without_existing_planning_settings"],
    }
