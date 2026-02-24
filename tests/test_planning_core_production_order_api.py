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
    ColorPlanningSettings,
    ElasticPlanningSettings,
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


def _seed_article_bundle_base(db_session, include_in_planning: bool = True):
    article = Article(code="PO-ART-1", name="PO-ART-1")
    db_session.add(article)
    db_session.flush()

    color_1 = Color(inner_code="PO-C1", pantone_code="BLACK-01", description="Black")
    color_2 = Color(inner_code="PO-C2", pantone_code="BLACK-02", description="Gray")
    db_session.add_all([color_1, color_2])
    db_session.flush()

    size_s = Size(label="PO-S", sort_order=1)
    size_m = Size(label="PO-M", sort_order=2)
    db_session.add_all([size_s, size_m])
    db_session.flush()

    sku_11 = SkuUnit(article_id=article.id, color_id=color_1.id, size_id=size_s.id)
    sku_12 = SkuUnit(article_id=article.id, color_id=color_1.id, size_id=size_m.id)
    sku_21 = SkuUnit(article_id=article.id, color_id=color_2.id, size_id=size_s.id)
    sku_22 = SkuUnit(article_id=article.id, color_id=color_2.id, size_id=size_m.id)
    db_session.add_all([sku_11, sku_12, sku_21, sku_22])
    db_session.flush()

    bundle_type = BundleType(code="PO-BT-1", name="PO-BT-1")
    db_session.add(bundle_type)
    db_session.flush()

    db_session.add_all(
        [
            BundleRecipe(article_id=article.id, bundle_type_id=bundle_type.id, color_id=color_1.id, position=1),
            BundleRecipe(article_id=article.id, bundle_type_id=bundle_type.id, color_id=color_2.id, position=2),
        ]
    )

    warehouse = Warehouse(code="PO-NSK", name="PO-NSK", type="local")
    db_session.add(warehouse)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            StockBalance(sku_unit_id=sku_11.id, warehouse_id=warehouse.id, quantity=10, updated_at=now),
            StockBalance(sku_unit_id=sku_12.id, warehouse_id=warehouse.id, quantity=10, updated_at=now),
            StockBalance(sku_unit_id=sku_21.id, warehouse_id=warehouse.id, quantity=10, updated_at=now),
            StockBalance(sku_unit_id=sku_22.id, warehouse_id=warehouse.id, quantity=10, updated_at=now),
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
            include_in_planning=include_in_planning,
            priority=2,
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
        "bundle_type": bundle_type,
        "size_s": size_s,
        "size_m": size_m,
        "color_1": color_1,
        "color_2": color_2,
    }


def _build_payload(article_id: int, bundle_type_id: int, size_s_id: int, size_m_id: int):
    return {
        "article_id": article_id,
        "planning_horizon_days": 90,
        "bundle_daily_sales": [
            {"bundle_type_id": bundle_type_id, "daily_sales": 20.0},
        ],
        "bundle_stock": [
            {"bundle_type_id": bundle_type_id, "wb_qty": 5, "local_qty": 5},
        ],
        "in_flight_supply": [],
        "size_weights": {
            str(size_s_id): 0.55,
            str(size_m_id): 0.45,
        },
        "overrides": {
            "target_coverage_days": 60,
            "service_level_percent": 90,
            "alert_threshold_days": 90,
            "lead_time_days": {
                "production": 30,
                "china_to_nsk": 30,
                "packaging": 3,
                "nsk_to_wb": 7,
            },
            "fabric_min_batch_qty_default": 7000,
            "elastic_min_batch_qty_default": 3000,
            "allow_order_with_buffer": True,
        },
    }


def test_production_order_proposal_happy_path(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "ok"
    assert body["article_id"] == seeded["article"].id
    assert body["recommendation"]["action"] in {"order_with_buffer", "order_minimum_only", "wait"}
    assert isinstance(body["recommendation"]["lines"], list)
    assert len(body["alternatives"]) >= 2
    assert body["explanation"]["summary"]


def test_production_order_proposal_skipped_when_article_excluded(client, db_session):
    seeded = _seed_article_bundle_base(db_session, include_in_planning=False)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "skipped"
    assert body["recommendation"] is None
    assert "исключен" in body["explanation"]["summary"].lower()


def test_production_order_proposal_applies_fabric_minimum(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ColorPlanningSettings(
            article_id=seeded["article"].id,
            color_id=seeded["color_1"].id,
            fabric_min_batch_qty=7500,
        )
    )
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    fabric_constraints = body["constraints_applied"]["fabric_min_batches"]
    assert fabric_constraints
    assert any(item["applied_min"] >= item["required"] for item in fabric_constraints)


def test_production_order_proposal_applies_elastic_minimum(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type = ElasticType(code="PO-EL-1", name="PO-EL-1")
    db_session.add(elastic_type)
    db_session.flush()

    db_session.add(
        ElasticPlanningSettings(
            article_id=seeded["article"].id,
            elastic_type_id=elastic_type.id,
            elastic_min_batch_qty=15000,
        )
    )
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    elastic_constraints = body["constraints_applied"]["elastic_min_batches"]
    assert elastic_constraints
    assert elastic_constraints[0]["applied_min"] == 15000
    assert elastic_constraints[0]["required"] < elastic_constraints[0]["applied_min"]


def test_production_order_proposal_returns_alternatives(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    actions = {item["action"] for item in body["alternatives"]}
    assert len(actions) >= 2
    assert actions.issubset({"wait", "order_with_buffer", "order_minimum_only"})


def test_production_order_proposal_in_flight_eta_stage_sensitivity(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["in_flight_supply"] = [
        {
            "article_id": seeded["article"].id,
            "color_id": seeded["color_1"].id,
            "size_id": seeded["size_s"].id,
            "qty": 100,
            "eta_days": 10,
            "stage": "nsk_to_wb",
        },
        {
            "article_id": seeded["article"].id,
            "color_id": seeded["color_2"].id,
            "size_id": seeded["size_m"].id,
            "qty": 100,
            "eta_days": 120,
            "stage": "production",
        },
    ]

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    in_flight_step = next(
        (step for step in body["explanation"]["steps"] if "In-flight вклад" in step),
        "",
    )
    assert "raw_qty=200" in in_flight_step
    assert "effective_qty=" in in_flight_step
    assert "lines=1" in in_flight_step
    assert "effective_qty=200" not in in_flight_step


def test_production_order_proposal_economic_buffer_policy(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload_without_buffer = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload_without_buffer["overrides"]["fabric_min_batch_qty_default"] = 0
    payload_without_buffer["overrides"]["elastic_min_batch_qty_default"] = 0
    payload_without_buffer["overrides"]["allow_order_with_buffer"] = False

    payload_with_buffer = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload_with_buffer["overrides"]["fabric_min_batch_qty_default"] = 0
    payload_with_buffer["overrides"]["elastic_min_batch_qty_default"] = 0
    payload_with_buffer["overrides"]["allow_order_with_buffer"] = True

    response_without = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload_without_buffer,
    )
    response_with = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload_with_buffer,
    )

    assert response_without.status_code == 200, response_without.text
    assert response_with.status_code == 200, response_with.text

    body_without = response_without.json()
    body_with = response_with.json()

    assert body_without["recommendation"] is not None
    assert body_with["recommendation"] is not None
    assert body_with["recommendation"]["total_units"] > body_without["recommendation"]["total_units"]

    buffer_step_without = next(
        (step for step in body_without["explanation"]["steps"] if "Economic buffer policy" in step),
        "",
    )
    buffer_step_with = next(
        (step for step in body_with["explanation"]["steps"] if "Economic buffer policy" in step),
        "",
    )

    assert "enabled=False" in buffer_step_without
    assert "economic_buffer_days=0" in buffer_step_without
    assert "enabled=True" in buffer_step_with
    assert "economic_buffer_days=0" not in buffer_step_with


def test_production_order_proposal_competition_aware_raw_stock_breakdown(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    competing_bundle_type = BundleType(code="PO-BT-2", name="PO-BT-2")
    db_session.add(competing_bundle_type)
    db_session.flush()

    db_session.add_all(
        [
            BundleRecipe(
                article_id=seeded["article"].id,
                bundle_type_id=competing_bundle_type.id,
                color_id=seeded["color_1"].id,
                position=1,
            ),
            BundleRecipe(
                article_id=seeded["article"].id,
                bundle_type_id=competing_bundle_type.id,
                color_id=seeded["color_2"].id,
                position=2,
            ),
        ]
    )
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "daily_sales": 20.0},
        {"bundle_type_id": competing_bundle_type.id, "daily_sales": 10.0},
    ]
    payload["bundle_stock"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "wb_qty": 5, "local_qty": 5},
        {"bundle_type_id": competing_bundle_type.id, "wb_qty": 0, "local_qty": 0},
    ]

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    raw_stock_step = next(
        (
            step
            for step in body["explanation"]["steps"]
            if "competition-aware by bundle" in step
        ),
        "",
    )
    assert "оценка сырьевого потенциала=20" in raw_stock_step
    assert f"{seeded['bundle_type'].id}:14" in raw_stock_step
    assert f"{competing_bundle_type.id}:6" in raw_stock_step


def test_production_order_proposal_validation_error(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json={
            "article_id": 1,
            "planning_horizon_days": 0,
            "bundle_daily_sales": [],
        },
    )
    assert response.status_code == 422, response.text
