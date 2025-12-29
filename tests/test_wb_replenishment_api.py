from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.schemas import WbReplenishmentRequest
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_color,
    create_size,
    create_sku,
    create_wb_mapping,
)
from app.models.models import StockBalance, Warehouse, SkuUnit


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


def _setup_article_with_data(db_session, code: str):
    article = create_article(db_session, code=code)
    color = create_color(db_session, inner_code=f"C-{code}")
    size = create_size(db_session, label=f"SZ-{code}", sort_order=1)
    sku = create_sku(db_session, article, color, size)
    return article, sku


def _add_nsk_stock(db_session, sku: SkuUnit, qty: int):
    wh = Warehouse(code="NSK", name="NSK", type="internal")
    db_session.add(wh)
    db_session.flush()
    from datetime import datetime, timezone

    sb = StockBalance(
        sku_unit_id=sku.id,
        warehouse_id=wh.id,
        quantity=qty,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(sb)
    db_session.flush()


def test_wb_replenishment_proposal_happy_path(client, db_session):
    target_date = date(2025, 1, 31)
    article, sku = _setup_article_with_data(db_session, code="REPL-API-BASE")
    wb_sku = "SKU-REPL-API-BASE"
    create_wb_mapping(db_session, article, wb_sku=wb_sku)

    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=5, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku, qty=100)

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "target_coverage_days": 30,
        "replenishment_strategy": "normal",
    }

    resp = client.post("/api/v1/wb/manager/proposal", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["target_date"] == target_date.isoformat()
    assert body["wb_arrival_date"] == target_date.isoformat()
    assert body["items"]

    item = body["items"][0]
    assert item["article_id"] == article.id
    assert item["recommended_qty"] >= 0


def test_wb_replenishment_proposal_invalid_dates(client, db_session):
    target_date = date(2025, 1, 31)
    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": "2025-01-01",  # earlier than target_date
    }

    resp = client.post("/api/v1/wb/manager/proposal", json=payload)
    assert resp.status_code == 400
    assert "wb_arrival_date cannot be earlier than target_date" in resp.json().get(
        "detail", ""
    )


def test_wb_replenishment_proposal_article_filter(client, db_session):
    target_date = date(2025, 1, 31)
    article1, sku1 = _setup_article_with_data(db_session, code="REPL-API-A1")
    article2, sku2 = _setup_article_with_data(db_session, code="REPL-API-A2")

    wb_sku1 = "SKU-REPL-API-A1"
    wb_sku2 = "SKU-REPL-API-A2"
    create_wb_mapping(db_session, article1, wb_sku=wb_sku1)
    create_wb_mapping(db_session, article2, wb_sku=wb_sku2)

    add_wb_sales(db_session, wb_sku=wb_sku1, day=target_date, sales_qty=10)
    add_wb_sales(db_session, wb_sku=wb_sku2, day=target_date, sales_qty=10)

    _add_nsk_stock(db_session, sku1, qty=100)
    _add_nsk_stock(db_session, sku2, qty=100)

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "article_ids": [article1.id],
    }

    resp = client.post("/api/v1/wb/manager/proposal", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["items"]
    assert {it["article_id"] for it in body["items"]} == {article1.id}
