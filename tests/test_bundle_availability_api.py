from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import BundleType, Warehouse
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


def test_bundle_availability_returns_404_for_unknown_article(client):
    response = client.get(
        "/api/v1/planning/bundle-availability",
        params={"article_id": 999999, "bundle_type_id": 1, "warehouse_id": 1},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": 999999,
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


def test_bundle_availability_returns_404_for_unknown_bundle_type(client, db_session):
    article = create_article(db_session, code="BA-ART-1")
    warehouse = Warehouse(code="BA-WH-1", name="BA-WH-1", type="internal")
    db_session.add(warehouse)
    db_session.commit()

    response = client.get(
        "/api/v1/planning/bundle-availability",
        params={"article_id": article.id, "bundle_type_id": 999999, "warehouse_id": warehouse.id},
    )
    assert response.status_code == 404, response.text
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


def test_bundle_availability_returns_404_for_unknown_warehouse(client, db_session):
    article = create_article(db_session, code="BA-ART-2")
    bundle_type = BundleType(code="BA-BT-1", name="BA-BT-1")
    db_session.add(bundle_type)
    db_session.commit()

    response = client.get(
        "/api/v1/planning/bundle-availability",
        params={"article_id": article.id, "bundle_type_id": bundle_type.id, "warehouse_id": 999999},
    )
    assert response.status_code == 404, response.text
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


def test_bundle_availability_returns_400_for_missing_bundle_recipe(client, db_session):
    article = create_article(db_session, code="BA-ART-3")
    bundle_type = BundleType(code="BA-BT-2", name="BA-BT-2")
    warehouse = Warehouse(code="BA-WH-2", name="BA-WH-2", type="internal")
    db_session.add_all([bundle_type, warehouse])
    db_session.commit()

    response = client.get(
        "/api/v1/planning/bundle-availability",
        params={"article_id": article.id, "bundle_type_id": bundle_type.id, "warehouse_id": warehouse.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_bundle_recipe",
        "message": "No bundle recipe defined for this article and bundle type",
        "article_id": article.id,
        "bundle_type_id": bundle_type.id,
        "field": "bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type identifier for bundle recipe lookup",
            "type": "int",
        },
        "next_steps": ["create_bundle_recipe_for_bundle_type"],
    }
