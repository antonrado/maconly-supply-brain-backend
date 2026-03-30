from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import BundleRecipe
from tests.test_utils import create_article, create_color


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


def test_get_bundle_recipe_returns_structured_404(client):
    response = client.get("/api/v1/bundle-recipe/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "bundle_recipe_not_found",
        "message": "BundleRecipe not found",
        "bundle_recipe_id": 999999,
        "next_steps": ["use_existing_bundle_recipe_id"],
    }


def test_create_bundle_recipe_returns_structured_409_for_duplicate_combination(client, db_session):
    article = create_article(db_session, code="BR-ART")
    color = create_color(db_session, inner_code="BR-COLOR")
    existing = BundleRecipe(article_id=article.id, bundle_type_id=1, color_id=color.id, position=1)
    db_session.add(existing)
    db_session.commit()

    response = client.post(
        "/api/v1/bundle-recipe/",
        json={"article_id": article.id, "bundle_type_id": 1, "color_id": color.id, "position": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bundle_recipe_combination_already_exists",
        "message": "BundleRecipe with same combination already exists",
        "field": "article_id,bundle_type_id,color_id,position",
        "article_id": article.id,
        "bundle_type_id": 1,
        "color_id": color.id,
        "position": 1,
        "next_steps": ["use_unique_bundle_recipe_combination"],
    }


def test_patch_bundle_recipe_returns_structured_409_for_duplicate_combination(client, db_session):
    article = create_article(db_session, code="BR-ART-2")
    color_one = create_color(db_session, inner_code="BR-COLOR-1")
    color_two = create_color(db_session, inner_code="BR-COLOR-2")

    existing = BundleRecipe(article_id=article.id, bundle_type_id=1, color_id=color_one.id, position=1)
    target = BundleRecipe(article_id=article.id, bundle_type_id=1, color_id=color_two.id, position=2)
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/bundle-recipe/{target.id}",
        json={"color_id": color_one.id, "position": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bundle_recipe_combination_already_exists",
        "message": "BundleRecipe with same combination already exists",
        "field": "article_id,bundle_type_id,color_id,position",
        "article_id": article.id,
        "bundle_type_id": 1,
        "color_id": color_one.id,
        "position": 1,
        "next_steps": ["use_unique_bundle_recipe_combination"],
    }
