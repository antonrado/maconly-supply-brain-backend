from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.models import BundleRecipe, BundleType, SkuUnit
from app.services.demand_engine import OBSERVATION_WINDOW_DAYS
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_color,
    create_global_planning_settings,
    create_planning_settings,
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


def test_legacy_core_proposal_stub_exposes_deprecation_headers(client, monkeypatch):
    from app.api.v1.endpoints import planning_core

    class _FakeProposal:
        def dict(self):
            return {
                "version": "v1",
                "generated_at": "stub",
                "inputs": {
                    "sales_window_days": None,
                    "horizon_days": None,
                },
                "summary": {
                    "total_skus": 0,
                    "total_units": 0,
                },
                "lines": [],
            }

    monkeypatch.setattr(
        planning_core.PlanningService,
        "build_proposal",
        lambda self, sales_window_days=None, horizon_days=None: _FakeProposal(),
    )

    response = client.post("/api/v1/planning/core/proposal", json={})

    assert response.status_code == 200, response.text
    assert response.headers["Deprecation"] == "true"
    assert response.headers["X-Planning-Fidelity"] == "stub_legacy_low_fidelity"
    assert response.headers["X-Planning-Successor"] == "/api/v1/planning/core/production-order/proposal"
    assert response.headers["X-Planning-Legacy-Phase"] == "deprecated_runtime_supported"
    body = response.json()
    assert body["status"] == "ok"


def test_openapi_hides_legacy_planning_paths_and_keeps_canonical_production_order_paths(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    assert "/api/v1/planning/core/proposal" not in paths
    assert "/api/v1/planning/order-proposal" not in paths
    assert "/api/v1/planning/core/production-order/proposal" in paths
    assert "/api/v1/planning/core/production-order/proposal/from-wb" in paths


def _setup_article_with_skus_and_planning(db_session, code: str = "E2E-ART-1"):
    """Create article with multiple SKUs and planning settings for end-to-end tests."""
    article = create_article(db_session, code=code)

    colors = [
        create_color(db_session, inner_code=f"{code}-C1"),
        create_color(db_session, inner_code=f"{code}-C2"),
    ]
    sizes = [
        create_size(db_session, label=f"S-{code}", sort_order=1),
        create_size(db_session, label=f"M-{code}", sort_order=2),
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


def _setup_article_with_canonical_from_wb_inputs(db_session, target_date: date):
    article = create_article(db_session, code="E2E-PO-CANONICAL")
    size = create_size(db_session, label="E2E-PO-CANONICAL-S", sort_order=1)
    color = create_color(db_session, inner_code="E2E-PO-CANONICAL-C1")
    create_sku(db_session, article, color, size)

    bundle_type = BundleType(code="E2E-PO-CANONICAL-BUNDLE", name="E2E-PO-CANONICAL-BUNDLE")
    db_session.add(bundle_type)
    db_session.flush()
    db_session.add(
        BundleRecipe(
            article_id=article.id,
            bundle_type_id=bundle_type.id,
            color_id=color.id,
            position=1,
        )
    )

    create_global_planning_settings(
        db_session,
        default_fabric_min_batch_qty=0,
        default_elastic_min_batch_qty=0,
        default_production_order_available_capital=10000,
    )
    create_article_planning_settings(
        db_session,
        article,
        target_coverage_days=60,
        lead_time_days=70,
        service_level_percent=90,
        production_order_production_cost_per_unit=100,
        production_order_logistics_cost_per_unit=20,
        production_order_wb_commission_percent_main=15,
        production_order_wb_commission_percent_assorti=15,
        production_order_average_realized_price_main=500,
        production_order_average_realized_price_assorti=500,
        production_order_available_capital=10000,
    )
    create_planning_settings(
        db_session,
        article,
        is_active=True,
        min_fabric_batch=0,
        min_elastic_batch=0,
        alert_threshold_days=90,
        strictness=1.0,
    )

    wb_sku = "SKU-END2END-PO-CANONICAL"
    create_wb_mapping(
        db_session,
        article,
        wb_sku=wb_sku,
        bundle_type_id=bundle_type.id,
        size_id=size.id,
    )
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date - timedelta(days=1), sales_qty=60)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=20)
    db_session.commit()

    return article, target_date


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
    assert resp_proposal.headers["Deprecation"] == "true"
    assert resp_proposal.headers["X-Planning-Fidelity"] == "legacy_live_low_fidelity"
    assert resp_proposal.headers["X-Planning-Successor"] == "/api/v1/planning/core/production-order/proposal"
    assert resp_proposal.headers["X-Planning-Legacy-Phase"] == "deprecated_runtime_supported"
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


def test_end_to_end_legacy_order_proposal_accepts_article_ids_scope(client, db_session):
    article_a = _setup_article_with_skus_and_planning(db_session, code="E2E-SCOPE-A")
    article_b = _setup_article_with_skus_and_planning(db_session, code="E2E-SCOPE-B")
    target_date = date(2025, 1, 31)

    create_wb_mapping(db_session, article_a, wb_sku="SKU-END2END-SCOPE-A")
    add_wb_sales(
        db_session,
        wb_sku="SKU-END2END-SCOPE-A",
        day=target_date,
        sales_qty=20,
    )
    add_wb_stock(db_session, wb_sku="SKU-END2END-SCOPE-A", stock_qty=0)

    create_wb_mapping(db_session, article_b, wb_sku="SKU-END2END-SCOPE-B")
    add_wb_sales(
        db_session,
        wb_sku="SKU-END2END-SCOPE-B",
        day=target_date,
        sales_qty=15,
    )
    add_wb_stock(db_session, wb_sku="SKU-END2END-SCOPE-B", stock_qty=0)
    db_session.commit()

    resp_proposal = client.get(
        "/api/v1/planning/order-proposal",
        params={
            "target_date": target_date.isoformat(),
            "explanation": False,
            "article_ids": [article_a.id],
        },
    )
    assert resp_proposal.status_code == 200, resp_proposal.text
    assert resp_proposal.headers["Deprecation"] == "true"
    assert resp_proposal.headers["X-Planning-Fidelity"] == "legacy_live_low_fidelity"
    assert resp_proposal.headers["X-Planning-Successor"] == "/api/v1/planning/core/production-order/proposal"
    assert resp_proposal.headers["X-Planning-Legacy-Phase"] == "deprecated_runtime_supported"

    proposal = resp_proposal.json()
    assert proposal["items"]
    assert {item["article_id"] for item in proposal["items"]} == {article_a.id}
    assert article_b.id not in {item["article_id"] for item in proposal["items"]}


def test_end_to_end_purchase_order_from_proposal_canonical_branch(client, db_session):
    target_date = date.today() + timedelta(days=45)
    article, target_date = _setup_article_with_canonical_from_wb_inputs(db_session, target_date)

    resp_canonical = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": article.id,
            "planning_horizon_days": 45,
            "explainability_mode": "full",
        },
    )
    assert resp_canonical.status_code == 200, resp_canonical.text
    canonical_body = resp_canonical.json()
    assert canonical_body["status"] == "ok"
    recommendation = canonical_body["recommendation"]
    assert recommendation is not None
    assert recommendation["lines"]

    resp_po = client.post(
        "/api/v1/purchase-order/from-proposal",
        json={
            "article_id": article.id,
            "target_date": target_date.isoformat(),
            "comment": "End-to-end canonical PO test",
            "explanation": True,
        },
    )
    assert resp_po.status_code == 201, resp_po.text
    po = resp_po.json()

    assert po["status"] == "draft"
    assert po["target_date"] == target_date.isoformat()
    assert po["comment"] == "End-to-end canonical PO test"
    assert po["items"]

    canonical_map = {
        (line["article_id"], line["color_id"], line["size_id"]): line["recommended_qty"]
        for line in recommendation["lines"]
        if line["recommended_qty"] > 0
    }
    po_map = {
        (item["article_id"], item["color_id"], item["size_id"]): item["quantity"]
        for item in po["items"]
    }

    assert canonical_map
    assert canonical_map == po_map


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
    assert resp_proposal.headers["Deprecation"] == "true"
    assert resp_proposal.headers["X-Planning-Fidelity"] == "legacy_live_low_fidelity"
    assert resp_proposal.headers["X-Planning-Successor"] == "/api/v1/planning/core/production-order/proposal"
    assert resp_proposal.headers["X-Planning-Legacy-Phase"] == "deprecated_runtime_supported"
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
