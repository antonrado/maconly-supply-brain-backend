from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import Article


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


def test_get_article_returns_structured_404(client):
    response = client.get("/api/v1/article/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": 999999,
        "next_steps": ["use_existing_article_id"],
    }


def test_create_article_returns_structured_409_for_duplicate_code(client, db_session):
    db_session.add(Article(code="ART-1", name="Article 1"))
    db_session.commit()

    response = client.post(
        "/api/v1/article/",
        json={"code": "ART-1", "name": "Duplicate"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "article_code_already_exists",
        "message": "Article code already exists",
        "field": "code",
        "article_code": "ART-1",
        "next_steps": ["use_unique_article_code"],
    }


def test_patch_article_returns_structured_409_for_duplicate_code(client, db_session):
    existing = Article(code="ART-1", name="Article 1")
    target = Article(code="ART-2", name="Article 2")
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/article/{target.id}",
        json={"code": "ART-1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "article_code_already_exists",
        "message": "Article code already exists",
        "field": "code",
        "article_code": "ART-1",
        "next_steps": ["use_unique_article_code"],
    }
