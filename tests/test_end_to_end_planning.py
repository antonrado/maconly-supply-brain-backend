from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import SkuUnit
from app.services.demand_engine import OBSERVATION_WINDOW_DAYS
from tests.test_utils import (
    create_article,
    create_article_planning_settings,
    create_color,
    create_global_planning_settings,
    create_planning_settings,
    create_size,
    create_sku,
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


def _setup_article_with_skus_and_planning(db_session):
    """Create article with multiple SKUs and planning settings for end-to-end tests."""
    article = create_article(db_session, code="E2E-ART-1")

    colors = [
        create_color(db_session, inner_code="E2E-C1"),
        create_color(db_session, inner_code="E2E-C2"),
    ]
    sizes = [
        create_size(db_session, label="S", sort_order=1),
        create_size(db_session, label="M", sort_order=2),
    ]

    for color in colors:
        for size in sizes:
            create_sku(db_session, article, color, size)

    create_global_planning_settings(db_session)
    create_article_planning_settings(db_session, article, target_coverage_days=10)
    create_planning_settings(
        db_session,
        article,
        is_active=True,
        min_fabric_batch=0,
        min_elastic_batch=0,
        strictness=1.0,
    )

    return article


def test_end_to_end_happy_path_wb_to_po(client, db_session):
    """Happy path: WB ingestion → demand → order proposal → purchase order draft."""
    article = _setup_article_with_skus_and_planning(db_session)
    target_date = date(2025, 1, 31)
    wb_sku = "SKU-END2END-1"

    # 1) WB article mapping import
    resp_map = client.post(
        "/api/v1/wb/article-mapping/import",
        json={
            "items": [
                {
                    "article_id": article.id,
                    "wb_sku": wb_sku,
                }
            ]
        },
    )
    assert resp_map.status_code == 200, resp_map.text
    body_map = resp_map.json()
    assert "inserted" in body_map and "updated" in body_map

    # 2) WB sales import
    resp_sales = client.post(
        "/api/v1/wb/sales-daily/import",
        json={
            "items": [
                {
                    "wb_sku": wb_sku,
                    "date": target_date.isoformat(),
                    "sales_qty": 20,
                    "revenue": 10000.0,
                }
            ]
        },
    )
    assert resp_sales.status_code == 200, resp_sales.text
    body_sales = resp_sales.json()
    assert "inserted" in body_sales and "updated" in body_sales

    # 3) WB stock import (zero stock to force deficit)
    resp_stock = client.post(
        "/api/v1/wb/stock/import",
        json={
            "items": [
                {
                    "wb_sku": wb_sku,
                    "stock_qty": 0,
                    "warehouse_id": None,
                    "warehouse_name": None,
                }
            ]
        },
    )
    assert resp_stock.status_code == 200, resp_stock.text
    body_stock = resp_stock.json()
    assert "inserted" in body_stock and "updated" in body_stock

    # 4) Demand calculation
    resp_demand = client.get(
        "/api/v1/planning/demand",
        params={
            "article_id": article.id,
            "target_date": target_date.isoformat(),
        },
    )
    assert resp_demand.status_code == 200, resp_demand.text
    demand = resp_demand.json()

    assert demand["article_id"] == article.id
    assert demand["avg_daily_sales"] > 0
    assert demand["forecast_demand"] > 0
    assert demand["current_stock"] == 0
    assert demand["deficit"] > 0
    assert demand["observation_window_days"] == OBSERVATION_WINDOW_DAYS
    assert demand["target_coverage_days"] == 10

    # 5) Order proposal
    resp_proposal = client.get(
        "/api/v1/planning/order-proposal",
        params={
            "target_date": target_date.isoformat(),
            "explanation": True,
        },
    )
    assert resp_proposal.status_code == 200, resp_proposal.text
    proposal = resp_proposal.json()

    assert proposal["target_date"] == target_date.isoformat()
    items = proposal["items"]
    assert items

    total_proposal_qty = sum(it["quantity"] for it in items)
    assert total_proposal_qty > 0
    assert {it["article_id"] for it in items} == {article.id}

    # All proposal (color_id, size_id) combinations must correspond to real SKUs
    sku_pairs = {
        (sku.color_id, sku.size_id)
        for sku in db_session.query(SkuUnit).filter(SkuUnit.article_id == article.id)
    }
    for it in items:
        assert (it["color_id"], it["size_id"]) in sku_pairs

    # 6) Create purchase order from proposal
    resp_po = client.post(
        "/api/v1/purchase-order/from-proposal",
        json={
            "target_date": target_date.isoformat(),
            "comment": "End-to-end PO test",
            "explanation": True,
        },
    )
    assert resp_po.status_code == 201, resp_po.text
    po = resp_po.json()

    assert po["status"] == "draft"
    assert po["target_date"] == target_date.isoformat()
    assert po["comment"] == "End-to-end PO test"
    assert po["items"]

    total_po_qty = sum(it["quantity"] for it in po["items"])
    assert total_po_qty > 0
    assert {it["article_id"] for it in po["items"]} == {article.id}

    for it in po["items"]:
        assert (it["color_id"], it["size_id"]) in sku_pairs


def test_end_to_end_zero_demand_creates_empty_po(client, db_session):
    """Zero WB demand: demand/ proposal empty, but PO draft is still created with no items."""
    article = _setup_article_with_skus_and_planning(db_session)
    target_date = date(2025, 1, 31)

    # No WB mappings and no sales/stock are created here.

    # Demand should be zero-deficit
    resp_demand = client.get(
        "/api/v1/planning/demand",
        params={
            "article_id": article.id,
            "target_date": target_date.isoformat(),
        },
    )
    assert resp_demand.status_code == 200, resp_demand.text
    demand = resp_demand.json()

    assert demand["article_id"] == article.id
    assert demand["avg_daily_sales"] == 0.0
    assert demand["deficit"] == 0

    # Order proposal should be empty
    resp_proposal = client.get(
        "/api/v1/planning/order-proposal",
        params={
            "target_date": target_date.isoformat(),
            "explanation": True,
        },
    )
    assert resp_proposal.status_code == 200, resp_proposal.text
    proposal = resp_proposal.json()

    assert proposal["items"] == []

    # Creating purchase order from empty proposal should succeed and yield empty items list
    resp_po = client.post(
        "/api/v1/purchase-order/from-proposal",
        json={
            "target_date": target_date.isoformat(),
            "comment": "End-to-end zero-demand PO",
            "explanation": True,
        },
    )
    assert resp_po.status_code == 201, resp_po.text
    po = resp_po.json()

    assert po["status"] == "draft"
    assert po["items"] == []
