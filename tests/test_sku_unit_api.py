from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import SkuUnit
from tests.test_utils import create_article, create_color, create_size, create_sku


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


def test_get_sku_unit_returns_structured_404(client):
    response = client.get("/api/v1/sku-unit/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "sku_unit_not_found",
        "message": "SkuUnit not found",
        "sku_unit_id": 999999,
        "next_steps": ["use_existing_sku_unit_id"],
    }


def test_create_sku_unit_returns_structured_409_for_duplicate_combination(client, db_session):
    article = create_article(db_session, code="SKU-ART")
    color = create_color(db_session, inner_code="SKU-COLOR")
    size = create_size(db_session, label="SKU-SIZE", sort_order=1)
    create_sku(db_session, article, color, size)
    db_session.commit()

    response = client.post(
        "/api/v1/sku-unit/",
        json={"article_id": article.id, "color_id": color.id, "size_id": size.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "sku_unit_combination_already_exists",
        "message": "SkuUnit combination already exists",
        "field": "article_id,color_id,size_id",
        "article_id": article.id,
        "color_id": color.id,
        "size_id": size.id,
        "next_steps": ["use_unique_sku_unit_article_color_size_combination"],
    }


def test_patch_sku_unit_returns_structured_409_for_duplicate_combination(client, db_session):
    article_one = create_article(db_session, code="SKU-ART-1")
    article_two = create_article(db_session, code="SKU-ART-2")
    color_one = create_color(db_session, inner_code="SKU-COLOR-1")
    color_two = create_color(db_session, inner_code="SKU-COLOR-2")
    size_one = create_size(db_session, label="SKU-SIZE-1", sort_order=1)
    size_two = create_size(db_session, label="SKU-SIZE-2", sort_order=2)

    existing = create_sku(db_session, article_one, color_one, size_one)
    target = create_sku(db_session, article_two, color_two, size_two)
    db_session.commit()

    response = client.patch(
        f"/api/v1/sku-unit/{target.id}",
        json={"article_id": article_one.id, "color_id": color_one.id, "size_id": size_one.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "sku_unit_combination_already_exists",
        "message": "SkuUnit combination already exists",
        "field": "article_id,color_id,size_id",
        "article_id": article_one.id,
        "color_id": color_one.id,
        "size_id": size_one.id,
        "next_steps": ["use_unique_sku_unit_article_color_size_combination"],
    }
