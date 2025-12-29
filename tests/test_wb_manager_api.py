from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)


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


def _setup_basic_wb_manager_article(db_session, code: str):
    article = create_article(db_session, code=code)
    color = create_color(db_session, inner_code=f"C-{code}")
    size = create_size(db_session, label=f"SZ-{code}", sort_order=1)
    create_sku(db_session, article, color, size)
    return article


def test_wb_manager_online_basic(client, db_session):
    target_date = date(2025, 1, 31)
    article = _setup_basic_wb_manager_article(db_session, code="MGR-API-BASE")
    wb_sku = "SKU-MGR-API-BASE"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    # Simple sales and stock
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=5)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=10, warehouse_id=1, warehouse_name="MSK")

    resp = client.get(
        "/api/v1/wb/manager/online",
        params={"target_date": target_date.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["target_date"] == target_date.isoformat()
    assert body["items"]

    item = body["items"][0]
    # Identification fields used by the frontend should be non-null
    assert isinstance(item["article_code"], str) and item["article_code"]
    assert isinstance(item["color_id"], int)
    assert isinstance(item["color_inner_code"], str) and item["color_inner_code"]
    assert isinstance(item["size_id"], int)
    assert isinstance(item["size_label"], str) and item["size_label"]

    assert item["article_id"] == article.id
    assert item["wb_stock_total"] == 10
    assert item["sales_1d"] == 5
    by_wh = {
        (w["warehouse_id"], w["warehouse_name"]): w["stock_qty"]
        for w in item["wb_stock_by_warehouse"]
    }
    assert by_wh[(1, "MSK")] == 10


def test_wb_manager_online_filters_by_article_ids(client, db_session):
    target_date = date(2025, 1, 31)
    article1 = _setup_basic_wb_manager_article(db_session, code="MGR-API-A1")
    article2 = _setup_basic_wb_manager_article(db_session, code="MGR-API-A2")

    wb_sku1 = "SKU-MGR-API-A1"
    wb_sku2 = "SKU-MGR-API-A2"
    create_wb_mapping(db_session, article1, wb_sku=wb_sku1)
    create_wb_mapping(db_session, article2, wb_sku=wb_sku2)

    add_wb_sales(db_session, wb_sku=wb_sku1, day=target_date, sales_qty=3)
    add_wb_sales(db_session, wb_sku=wb_sku2, day=target_date, sales_qty=7)

    resp = client.get(
        "/api/v1/wb/manager/online",
        params={
            "target_date": target_date.isoformat(),
            "article_ids": [article1.id],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert {item["article_id"] for item in body["items"]} == {article1.id}


def test_wb_manager_online_no_wb_data(client, db_session):
    target_date = date(2025, 1, 31)
    article = _setup_basic_wb_manager_article(db_session, code="MGR-API-NO-WB")

    resp = client.get(
        "/api/v1/wb/manager/online",
        params={"target_date": target_date.isoformat(), "article_ids": [article.id]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["items"]
    item = body["items"][0]

    assert item["article_id"] == article.id
    assert item["wb_sku"] is None
    assert item["sales_30d"] == 0
    assert item["wb_stock_total"] == 0
    assert item["oos_risk_level"] == "green"
