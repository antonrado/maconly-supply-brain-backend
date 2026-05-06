from __future__ import annotations

from datetime import date, timedelta, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import BundleRecipe, BundleType, StockBalance, Warehouse
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


def _add_nsk_stock(db_session, sku_id: int, qty: int, code: str) -> None:
    warehouse = Warehouse(code=code, name="NSK", type="internal")
    db_session.add(warehouse)
    db_session.flush()
    db_session.add(
        StockBalance(
            sku_unit_id=sku_id,
            warehouse_id=warehouse.id,
            quantity=qty,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()


def _setup_blocked_canonical_article(db_session):
    target_date = date(2025, 1, 31)
    article = create_article(db_session, code="SHIP-CMP-BLOCK")
    color = create_color(db_session, inner_code="SHIP-CMP-BLOCK-C")
    size = create_size(db_session, label="SHIP-CMP-BLOCK-S", sort_order=1)
    sku = create_sku(db_session, article, color, size)

    wb_sku = "SKU-SHIP-CMP-BLOCK"
    create_wb_mapping(
        db_session,
        article,
        wb_sku=wb_sku,
        color_id=color.id,
        size_id=size.id,
    )
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date, sales_qty=10)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=5, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku.id, qty=100, code="NSK-SHIP-CMP-BLOCK")
    db_session.commit()

    return article, target_date


def _setup_ok_canonical_article(db_session):
    target_date = date.today() + timedelta(days=45)
    article = create_article(db_session, code="SHIP-CMP-OK")
    color = create_color(db_session, inner_code="SHIP-CMP-OK-C")
    size = create_size(db_session, label="SHIP-CMP-OK-S", sort_order=1)
    sku = create_sku(db_session, article, color, size)

    bundle_type = BundleType(code="SHIP-CMP-OK-BT", name="SHIP-CMP-OK-BT")
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
        production_order_wb_commission_percent_main=0.15,
        production_order_wb_commission_percent_assorti=0.15,
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

    wb_sku = "SKU-SHIP-CMP-OK"
    create_wb_mapping(
        db_session,
        article,
        wb_sku=wb_sku,
        bundle_type_id=bundle_type.id,
        color_id=color.id,
        size_id=size.id,
    )
    add_wb_sales(db_session, wb_sku=wb_sku, day=target_date - timedelta(days=1), sales_qty=60)
    add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=20, warehouse_id=1, warehouse_name="MSK")
    _add_nsk_stock(db_session, sku.id, qty=200, code="NSK-SHIP-CMP-OK")
    db_session.commit()

    return article, target_date


def test_shipment_from_proposal_comparison_reports_blocked_canonical_difference(client, db_session):
    article, target_date = _setup_blocked_canonical_article(db_session)

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "target_coverage_days": 30,
        "min_coverage_days": 7,
        "replenishment_strategy": "normal",
        "zero_sales_policy": "ignore",
        "max_coverage_days_after": 60,
    }

    resp = client.post("/api/v1/wb/manager/shipment/from-proposal/comparison", json=payload)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["target_date"] == target_date.isoformat()
    assert body["scope_normalization"]["normalization_strategy"] == "replenishment_output_article_ids"
    assert body["scope_normalization"]["normalized_article_ids"] == [article.id]
    assert body["replenishment_items"]
    assert len(body["article_comparisons"]) == 1

    article_comparison = body["article_comparisons"][0]
    assert article_comparison["article_id"] == article.id
    assert article_comparison["canonical_status"] == "blocked"
    assert article_comparison["canonical_blocker_code"] == "no_wb_mapped_bundle_types"
    assert article_comparison["divergence_category"] == "canonical_blocked"
    assert article_comparison["replenishment_total_recommended_qty"] > 0
    assert body["divergence_summary"] == {
        "has_divergence": True,
        "article_count": 1,
        "divergent_article_count": 1,
        "categories": {"canonical_blocked": 1},
    }


def test_shipment_from_proposal_comparison_reports_ok_canonical_result_with_requested_scope(client, db_session):
    article, target_date = _setup_ok_canonical_article(db_session)

    payload = {
        "target_date": target_date.isoformat(),
        "wb_arrival_date": target_date.isoformat(),
        "target_coverage_days": 30,
        "min_coverage_days": 7,
        "replenishment_strategy": "normal",
        "zero_sales_policy": "ignore",
        "max_coverage_days_after": 60,
        "article_ids": [article.id],
    }

    resp = client.post("/api/v1/wb/manager/shipment/from-proposal/comparison", json=payload)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["scope_normalization"]["requested_article_ids"] == [article.id]
    assert body["scope_normalization"]["normalized_article_ids"] == [article.id]
    assert body["scope_normalization"]["normalization_strategy"] == "requested_article_ids"
    assert body["scope_normalization"]["comparison_as_of_date"] == target_date.isoformat()
    assert body["scope_normalization"]["canonical_planning_horizon_days"] >= 1
    assert len(body["article_comparisons"]) == 1

    article_comparison = body["article_comparisons"][0]
    assert article_comparison["article_id"] == article.id
    assert article_comparison["canonical_status"] == "ok"
    assert article_comparison["canonical_blocker_code"] is None
    assert article_comparison["canonical_action"] in {"wait", "order_with_buffer", "order_minimum_only"}
    assert article_comparison["canonical_risk_level"] in {"ok", "warning", "critical", "overstock", "no_data"}
    assert article_comparison["canonical_arrival_projection_status"] in {
        "safe_cover_until_arrival",
        "shortage_before_arrival",
        "no_demand",
    }
    assert isinstance(article_comparison["line_comparisons"], list)
    assert body["divergence_summary"]["article_count"] == 1


def test_shipment_from_proposal_comparison_rejects_invalid_dates(client):
    payload = {
        "target_date": "2025-01-31",
        "wb_arrival_date": "2025-01-01",
        "target_coverage_days": 30,
        "min_coverage_days": 7,
        "replenishment_strategy": "normal",
        "zero_sales_policy": "ignore",
        "max_coverage_days_after": 60,
    }

    resp = client.post("/api/v1/wb/manager/shipment/from-proposal/comparison", json=payload)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == {
        "code": "wb_arrival_date_before_target_date",
        "message": "wb_arrival_date cannot be earlier than target_date",
        "field": "wb_arrival_date",
        "field_metadata": {
            "description": "Requested WB arrival date",
            "type": "date",
        },
        "target_date": "2025-01-31",
        "wb_arrival_date": "2025-01-01",
        "next_steps": ["use_wb_arrival_date_on_or_after_target_date"],
    }
