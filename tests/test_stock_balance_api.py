from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import StockBalance, Warehouse
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


def _create_sku_and_warehouse(db_session):
    article = create_article(db_session, code="SB-ART")
    color = create_color(db_session, inner_code="BLK-SB")
    size = create_size(db_session, label="SB-SIZE", sort_order=1)
    sku = create_sku(db_session, article, color, size)
    warehouse = Warehouse(code="SB-NSK", name="Stock NSK", type="internal")
    db_session.add(warehouse)
    db_session.commit()
    db_session.refresh(sku)
    db_session.refresh(warehouse)
    return sku, warehouse


def test_get_stock_balance_returns_structured_404(client):
    response = client.get("/api/v1/stock-balance/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "stock_balance_not_found",
        "message": "StockBalance not found",
        "stock_balance_id": 999999,
        "field": "stock_balance_id",
        "field_metadata": {
            "description": "Requested stock balance identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_stock_balance_id"],
    }


def test_create_stock_balance_returns_structured_409_for_duplicate_pair(client, db_session):
    sku, warehouse = _create_sku_and_warehouse(db_session)
    db_session.add(
        StockBalance(
            sku_unit_id=sku.id,
            warehouse_id=warehouse.id,
            quantity=10,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/stock-balance/",
        json={
            "sku_unit_id": sku.id,
            "warehouse_id": warehouse.id,
            "quantity": 20,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stock_balance_pair_already_exists",
        "message": "StockBalance for this sku_unit and warehouse already exists",
        "field": "sku_unit_id,warehouse_id",
        "field_metadata": {
            "description": "Requested stock balance uniqueness pair",
            "type": "tuple[int,int]",
        },
        "sku_unit_id": sku.id,
        "warehouse_id": warehouse.id,
        "next_steps": ["use_unique_stock_balance_sku_unit_warehouse_pair"],
    }


def test_patch_stock_balance_returns_structured_409_for_duplicate_pair(client, db_session):
    sku_one, warehouse_one = _create_sku_and_warehouse(db_session)

    article = create_article(db_session, code="SB-ART-2")
    color = create_color(db_session, inner_code="WHT-SB")
    size = create_size(db_session, label="SB-SIZE-2", sort_order=2)
    warehouse_two = Warehouse(code="SB-MSK", name="Stock MSK", type="internal")
    sku_two = create_sku(db_session, article, color, size)
    db_session.add(warehouse_two)
    db_session.flush()

    existing = StockBalance(
        sku_unit_id=sku_one.id,
        warehouse_id=warehouse_one.id,
        quantity=10,
        updated_at=datetime.now(timezone.utc),
    )
    target = StockBalance(
        sku_unit_id=sku_two.id,
        warehouse_id=warehouse_two.id,
        quantity=5,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add_all([existing, target])
    db_session.commit()

    response = client.patch(
        f"/api/v1/stock-balance/{target.id}",
        json={"sku_unit_id": sku_one.id, "warehouse_id": warehouse_one.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stock_balance_pair_already_exists",
        "message": "StockBalance for this sku_unit and warehouse already exists",
        "field": "sku_unit_id,warehouse_id",
        "field_metadata": {
            "description": "Requested stock balance uniqueness pair",
            "type": "tuple[int,int]",
        },
        "sku_unit_id": sku_one.id,
        "warehouse_id": warehouse_one.id,
        "next_steps": ["use_unique_stock_balance_sku_unit_warehouse_pair"],
    }
