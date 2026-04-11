from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app


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


def test_wb_article_mapping_import_rejects_unknown_article_with_structured_detail(client):
    response = client.post(
        "/api/v1/wb/article-mapping/import",
        json={
            "items": [
                {
                    "article_id": 999999999,
                    "wb_sku": "WB-MISSING-ARTICLE-1",
                    "bundle_type_id": None,
                    "color_id": None,
                    "size_id": None,
                }
            ]
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "wb_mapping_article_not_found",
        "message": "Referenced article_id does not exist",
        "field": "article_id",
        "field_metadata": {
            "description": "Article identifier in article-to-WB mapping import payload",
            "type": "int",
        },
        "article_id": 999999999,
        "wb_sku": "WB-MISSING-ARTICLE-1",
        "next_steps": ["use_existing_article_id"],
    }
