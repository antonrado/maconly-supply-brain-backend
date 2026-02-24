from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import (
    Article,
    ArticlePlanningSettings,
    BundleRecipe,
    BundleType,
    Color,
    ElasticType,
    GlobalPlanningSettings,
    PlanningSettings,
    Size,
    SkuUnit,
    StockBalance,
    Warehouse,
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


def _seed_scope(db_session):
    article = Article(code="PO-SET-1", name="PO-SET-1")
    article_other = Article(code="PO-SET-2", name="PO-SET-2")
    db_session.add_all([article, article_other])
    db_session.flush()

    color_1 = Color(inner_code="PO-SC-1", pantone_code="P-1", description="C1")
    color_2 = Color(inner_code="PO-SC-2", pantone_code="P-2", description="C2")
    db_session.add_all([color_1, color_2])
    db_session.flush()

    size_s = Size(label="PO-SZ-S", sort_order=1)
    size_m = Size(label="PO-SZ-M", sort_order=2)
    db_session.add_all([size_s, size_m])
    db_session.flush()

    sku_11 = SkuUnit(article_id=article.id, color_id=color_1.id, size_id=size_s.id)
    sku_12 = SkuUnit(article_id=article.id, color_id=color_1.id, size_id=size_m.id)
    sku_21 = SkuUnit(article_id=article.id, color_id=color_2.id, size_id=size_s.id)
    sku_22 = SkuUnit(article_id=article.id, color_id=color_2.id, size_id=size_m.id)
    sku_other = SkuUnit(article_id=article_other.id, color_id=color_1.id, size_id=size_s.id)
    db_session.add_all([sku_11, sku_12, sku_21, sku_22, sku_other])
    db_session.flush()

    elastic_1 = ElasticType(code="PO-EL-A", name="PO-EL-A")
    elastic_2 = ElasticType(code="PO-EL-B", name="PO-EL-B")
    db_session.add_all([elastic_1, elastic_2])
    db_session.flush()

    bundle_type = BundleType(code="PO-SBT-1", name="PO-SBT-1")
    db_session.add(bundle_type)
    db_session.flush()

    db_session.add_all(
        [
            BundleRecipe(article_id=article.id, bundle_type_id=bundle_type.id, color_id=color_1.id, position=1),
            BundleRecipe(article_id=article.id, bundle_type_id=bundle_type.id, color_id=color_2.id, position=2),
        ]
    )

    warehouse = Warehouse(code="PO-SET-NSK", name="PO-SET-NSK", type="local")
    db_session.add(warehouse)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            StockBalance(sku_unit_id=sku_11.id, warehouse_id=warehouse.id, quantity=20, updated_at=now),
            StockBalance(sku_unit_id=sku_12.id, warehouse_id=warehouse.id, quantity=15, updated_at=now),
            StockBalance(sku_unit_id=sku_21.id, warehouse_id=warehouse.id, quantity=18, updated_at=now),
            StockBalance(sku_unit_id=sku_22.id, warehouse_id=warehouse.id, quantity=12, updated_at=now),
        ]
    )

    db_session.add(
        GlobalPlanningSettings(
            default_target_coverage_days=60,
            default_lead_time_days=70,
            default_service_level_percent=90,
            default_fabric_min_batch_qty=7000,
            default_elastic_min_batch_qty=3000,
        )
    )
    db_session.add(
        ArticlePlanningSettings(
            article_id=article.id,
            include_in_planning=True,
            priority=1,
            target_coverage_days=60,
            lead_time_days=70,
            service_level_percent=90,
        )
    )
    db_session.add(
        PlanningSettings(
            article_id=article.id,
            is_active=True,
            min_fabric_batch=0,
            min_elastic_batch=0,
            alert_threshold_days=90,
            safety_stock_days=0,
            strictness=1.0,
            notes=None,
        )
    )

    db_session.commit()

    return {
        "article": article,
        "article_other": article_other,
        "color_1": color_1,
        "size_s": size_s,
        "size_m": size_m,
        "sku_22": sku_22,
        "sku_other": sku_other,
        "elastic_1": elastic_1,
        "elastic_2": elastic_2,
        "bundle_type": bundle_type,
    }


def test_production_order_settings_get_empty(client, db_session):
    seeded = _seed_scope(db_session)

    response = client.get(f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["article_id"] == seeded["article"].id
    assert body["size_weights"] == []
    assert body["elastic_bindings"] == []
    assert body["in_flight_supply_defaults"] == []


def test_production_order_settings_put_and_get_roundtrip(client, db_session):
    seeded = _seed_scope(db_session)

    payload = {
        "size_weights": [
            {"size_id": seeded["size_s"].id, "weight": 0.6},
            {"size_id": seeded["size_m"].id, "weight": 0.4},
        ],
        "elastic_bindings": [
            {
                "elastic_type_id": seeded["elastic_1"].id,
                "color_id": seeded["color_1"].id,
                "is_active": True,
            },
            {
                "elastic_type_id": seeded["elastic_2"].id,
                "sku_unit_id": seeded["sku_22"].id,
                "is_active": True,
            },
        ],
        "in_flight_supply_defaults": [
            {
                "color_id": seeded["color_1"].id,
                "size_id": seeded["size_s"].id,
                "qty": 150,
                "eta_days": 25,
                "stage": "production",
                "is_active": True,
            }
        ],
    }

    put_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}",
        json=payload,
    )
    assert put_response.status_code == 200, put_response.text

    body = put_response.json()
    assert len(body["size_weights"]) == 2
    assert len(body["elastic_bindings"]) == 2
    assert len(body["in_flight_supply_defaults"]) == 1

    get_response = client.get(f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}")
    assert get_response.status_code == 200, get_response.text

    get_body = get_response.json()
    assert get_body == body


def test_production_order_settings_rejects_sku_from_other_article(client, db_session):
    seeded = _seed_scope(db_session)

    payload = {
        "size_weights": [],
        "elastic_bindings": [
            {
                "elastic_type_id": seeded["elastic_1"].id,
                "sku_unit_id": seeded["sku_other"].id,
                "is_active": True,
            }
        ],
        "in_flight_supply_defaults": [],
    }

    response = client.put(
        f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}",
        json=payload,
    )
    assert response.status_code == 400, response.text
    assert "does not belong to article" in response.json()["detail"]


def test_production_order_proposal_uses_admin_defaults(client, db_session):
    seeded = _seed_scope(db_session)

    settings_payload = {
        "size_weights": [
            {"size_id": seeded["size_s"].id, "weight": 0.75},
            {"size_id": seeded["size_m"].id, "weight": 0.25},
        ],
        "elastic_bindings": [],
        "in_flight_supply_defaults": [
            {
                "color_id": seeded["color_1"].id,
                "size_id": seeded["size_s"].id,
                "qty": 200,
                "eta_days": 15,
                "stage": "china_to_nsk",
                "is_active": True,
            }
        ],
    }

    save_resp = client.put(
        f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}",
        json=settings_payload,
    )
    assert save_resp.status_code == 200, save_resp.text

    proposal_payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "bundle_daily_sales": [
            {"bundle_type_id": seeded["bundle_type"].id, "daily_sales": 18.0},
        ],
        "bundle_stock": [
            {"bundle_type_id": seeded["bundle_type"].id, "wb_qty": 5, "local_qty": 5},
        ],
        "size_weights": {},
        "in_flight_supply": [],
    }

    response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=proposal_payload,
    )
    assert response.status_code == 200, response.text

    body = response.json()
    steps = body["explanation"]["steps"]
    assert any("size_weights=admin_defaults" in step for step in steps)
    assert any("in_flight=admin_defaults" in step for step in steps)
