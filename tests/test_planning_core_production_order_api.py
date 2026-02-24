from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.models import (
    Article,
    ArticleWbMapping,
    ArticlePlanningSettings,
    BundleRecipe,
    BundleType,
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    ElasticType,
    GlobalPlanningSettings,
    PlanningSettings,
    ProductionOrderElasticBinding,
    Size,
    SkuUnit,
    StockBalance,
    WbSalesDaily,
    WbStock,
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


def test_production_order_proposal_elastic_binding_scope_selects_bound_type(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type_1 = ElasticType(code="PO-EL-BIND-1", name="PO-EL-BIND-1")
    elastic_type_2 = ElasticType(code="PO-EL-BIND-2", name="PO-EL-BIND-2")
    db_session.add_all([elastic_type_1, elastic_type_2])
    db_session.flush()

    db_session.add_all(
        [
            ElasticPlanningSettings(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type_1.id,
                elastic_min_batch_qty=12000,
            ),
            ElasticPlanningSettings(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type_2.id,
                elastic_min_batch_qty=20000,
            ),
            ProductionOrderElasticBinding(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type_1.id,
                color_id=seeded["color_1"].id,
                is_active=True,
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
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    elastic_constraints = body["constraints_applied"]["elastic_min_batches"]
    assert elastic_constraints
    assert elastic_constraints[0]["applied_min"] == 12000

    scope_step = next(
        (step for step in body["explanation"]["steps"] if "Elastic scope" in step),
        "",
    )
    uplift_step = next(
        (step for step in body["explanation"]["steps"] if "Elastic uplift" in step),
        "",
    )
    assert "mode=binding_scope" in scope_step
    assert f"applicable_types=[{elastic_type_1.id}]" in scope_step
    assert "scoped_settings=1" in scope_step
    assert "scoped_lines=2" in scope_step
    assert "scope=binding_scope" in uplift_step
    assert "affected_lines=2" in uplift_step
    assert "line_alloc={" in uplift_step
    assert f"({seeded['color_1'].id}, {seeded['size_s'].id}):" in uplift_step
    assert f"({seeded['color_1'].id}, {seeded['size_m'].id}):" in uplift_step

    meta = body["explanation"]["meta"]
    assert meta["elastic_scope"]["mode"] == "binding_scope"
    assert meta["elastic_scope"]["applicable_types"] == [elastic_type_1.id]
    assert meta["elastic_scope"]["scoped_settings"] == 1
    assert meta["elastic_scope"]["scoped_lines"] == 2
    assert meta["elastic_uplift"]["scope"] == "binding_scope"
    assert meta["elastic_uplift"]["affected_lines"] == 2
    alloc_pairs = {
        (item["color_id"], item["size_id"])
        for item in meta["elastic_uplift"]["line_alloc"]
    }
    assert alloc_pairs == {
        (seeded["color_1"].id, seeded["size_s"].id),
        (seeded["color_1"].id, seeded["size_m"].id),
    }


def test_production_order_proposal_elastic_binding_scope_uplift_only_scoped_lines(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    baseline_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert baseline_response.status_code == 200, baseline_response.text

    baseline_body = baseline_response.json()
    baseline_lines = baseline_body["recommendation"]["lines"]

    baseline_totals_by_color: dict[int, int] = {}
    for line in baseline_lines:
        baseline_totals_by_color[line["color_id"]] = (
            baseline_totals_by_color.get(line["color_id"], 0) + line["recommended_qty"]
        )

    elastic_type = ElasticType(code="PO-EL-SCOPE-ONLY", name="PO-EL-SCOPE-ONLY")
    db_session.add(elastic_type)
    db_session.flush()

    db_session.add_all(
        [
            ElasticPlanningSettings(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                elastic_min_batch_qty=22000,
            ),
            ProductionOrderElasticBinding(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                color_id=seeded["color_1"].id,
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    scoped_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert scoped_response.status_code == 200, scoped_response.text

    scoped_body = scoped_response.json()
    scoped_lines = scoped_body["recommendation"]["lines"]

    scoped_totals_by_color: dict[int, int] = {}
    for line in scoped_lines:
        scoped_totals_by_color[line["color_id"]] = (
            scoped_totals_by_color.get(line["color_id"], 0) + line["recommended_qty"]
        )

    color_1_id = seeded["color_1"].id
    color_2_id = seeded["color_2"].id

    assert scoped_totals_by_color.get(color_1_id, 0) > baseline_totals_by_color.get(color_1_id, 0)
    assert scoped_totals_by_color.get(color_2_id, 0) == baseline_totals_by_color.get(color_2_id, 0)


def test_production_order_proposal_elastic_binding_scope_uplift_only_scoped_sku(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    baseline_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert baseline_response.status_code == 200, baseline_response.text

    baseline_body = baseline_response.json()
    baseline_by_key: dict[tuple[int, int], int] = {
        (line["color_id"], line["size_id"]): line["recommended_qty"]
        for line in baseline_body["recommendation"]["lines"]
    }

    sku_scope = (
        db_session.query(SkuUnit)
        .filter(
            SkuUnit.article_id == seeded["article"].id,
            SkuUnit.color_id == seeded["color_1"].id,
            SkuUnit.size_id == seeded["size_s"].id,
        )
        .one()
    )

    elastic_type = ElasticType(code="PO-EL-SCOPE-SKU", name="PO-EL-SCOPE-SKU")
    db_session.add(elastic_type)
    db_session.flush()

    db_session.add_all(
        [
            ElasticPlanningSettings(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                elastic_min_batch_qty=22000,
            ),
            ProductionOrderElasticBinding(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                sku_unit_id=sku_scope.id,
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    scoped_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert scoped_response.status_code == 200, scoped_response.text

    scoped_body = scoped_response.json()
    scoped_by_key: dict[tuple[int, int], int] = {
        (line["color_id"], line["size_id"]): line["recommended_qty"]
        for line in scoped_body["recommendation"]["lines"]
    }

    scoped_key = (seeded["color_1"].id, seeded["size_s"].id)
    assert scoped_by_key[scoped_key] > baseline_by_key[scoped_key]

    for key, baseline_qty in baseline_by_key.items():
        if key == scoped_key:
            continue
        assert scoped_by_key[key] == baseline_qty

    scope_step = next(
        (step for step in scoped_body["explanation"]["steps"] if "Elastic scope" in step),
        "",
    )
    uplift_step = next(
        (step for step in scoped_body["explanation"]["steps"] if "Elastic uplift" in step),
        "",
    )
    assert "scoped_lines=1" in scope_step
    assert "scope=binding_scope" in uplift_step
    assert "affected_lines=1" in uplift_step
    assert "line_alloc={" in uplift_step
    assert f"{scoped_key}:" in uplift_step


def test_production_order_proposal_elastic_binding_scope_skips_when_no_match(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type = ElasticType(code="PO-EL-NOMATCH", name="PO-EL-NOMATCH")
    color_3 = Color(inner_code="PO-C3", pantone_code="BLACK-03", description="Blue")
    db_session.add_all([elastic_type, color_3])
    db_session.flush()

    db_session.add_all(
        [
            ElasticPlanningSettings(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                elastic_min_batch_qty=15000,
            ),
            ProductionOrderElasticBinding(
                article_id=seeded["article"].id,
                elastic_type_id=elastic_type.id,
                color_id=color_3.id,
                is_active=True,
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
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["constraints_applied"]["elastic_min_batches"] == []

    scope_step = next(
        (step for step in body["explanation"]["steps"] if "Elastic scope" in step),
        "",
    )
    uplift_step = next(
        (step for step in body["explanation"]["steps"] if "Elastic uplift" in step),
        "",
    )
    assert "mode=binding_scope" in scope_step
    assert "applicable_types=[]" in scope_step
    assert "scoped_settings=0" in scope_step
    assert "delta=0" in uplift_step
    assert "scope=none" in uplift_step
    assert "affected_lines=0" in uplift_step
    assert "line_alloc={}" in uplift_step

    meta = body["explanation"]["meta"]
    assert meta["elastic_scope"]["mode"] == "binding_scope"
    assert meta["elastic_scope"]["applicable_types"] == []
    assert meta["elastic_scope"]["scoped_settings"] == 0
    assert meta["elastic_uplift"]["delta"] == 0
    assert meta["elastic_uplift"]["scope"] == "none"
    assert meta["elastic_uplift"]["affected_lines"] == 0
    assert meta["elastic_uplift"]["line_alloc"] == []


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


def test_production_order_proposal_applies_safety_stock_days_to_reorder_policy(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0
    payload["overrides"]["allow_order_with_buffer"] = False

    response_without_safety_stock = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload,
    )
    assert response_without_safety_stock.status_code == 200, response_without_safety_stock.text

    planning_settings = (
        db_session.query(PlanningSettings)
        .filter(PlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    planning_settings.safety_stock_days = 21
    db_session.commit()

    response_with_safety_stock = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload,
    )
    assert response_with_safety_stock.status_code == 200, response_with_safety_stock.text

    body_without = response_without_safety_stock.json()
    body_with = response_with_safety_stock.json()

    assert body_without["recommendation"] is not None
    assert body_with["recommendation"] is not None
    assert body_with["recommendation"]["total_units"] > body_without["recommendation"]["total_units"]

    reorder_step = next(
        (step for step in body_with["explanation"]["steps"] if "Reorder policy" in step),
        "",
    )
    assert "lead_time_days=70" in reorder_step
    assert "safety_stock_days=21" in reorder_step
    assert "reorder_point_days=91" in reorder_step

    assert body_with["explanation"]["meta"]["reorder_policy"] == {
        "lead_time_days_total": 70,
        "safety_stock_days": 21,
        "reorder_point_days": 91,
    }


def test_production_order_proposal_exposes_layer1_and_layer2_meta(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]

    layer1 = meta["layer_1_stock_health"]
    layer2 = meta["layer_2_allocation"]

    assert layer1["summary"]["sku_count"] == 4
    assert len(layer1["metrics"]) == 4
    for metric in layer1["metrics"]:
        assert {
            "color_id",
            "size_id",
            "velocity_main",
            "velocity_assorti",
            "coverage_days",
            "current_stock",
            "in_flight",
            "eta_days",
            "gross_margin",
            "capital_locked",
            "stockout_risk",
            "overstock_risk",
        }.issubset(metric.keys())
        assert metric["velocity_assorti"] == 0.0

    assert layer1["proxies"] == {
        "main_margin": 1.0,
        "assorti_margin": 0.85,
        "unit_capital": 1.0,
    }

    assert layer2["method"] == "time_window_gmroi_proxy"
    assert len(layer2["decisions"]) == 4
    assert layer2["summary"] == {"main": 4, "assorti": 0, "hold": 0}

    layer1_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 1 stock health" in step),
        "",
    )
    layer2_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert "sku_count=4" in layer1_step
    assert "main=4" in layer2_step


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


def test_production_order_proposal_uses_wb_bundle_stock_fallback(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=25,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_stock"] = []

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    source_step = next(
        (step for step in body["explanation"]["steps"] if "Источник параметров" in step),
        "",
    )
    stock_step = next(
        (step for step in body["explanation"]["steps"] if "ready stock наборов" in step),
        "",
    )

    assert "bundle_stock=wb_defaults" in source_step
    assert "ready stock наборов (WB+локальный)=25" in stock_step


def test_production_order_proposal_from_wb_endpoint(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-10",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )
    source_step = next(
        (step for step in body["explanation"]["steps"] if "Источник параметров" in step),
        "",
    )
    stock_step = next(
        (step for step in body["explanation"]["steps"] if "ready stock наборов" in step),
        "",
    )

    assert "observation_window_days=30" in wb_adapter_step
    assert "freshness_mode=warn" in wb_adapter_step
    assert "requested_as_of_date=2026-01-10" in wb_adapter_step
    assert "as_of_date=2026-01-10" in wb_adapter_step
    assert "as_of_source=request" in wb_adapter_step
    assert "sales_window=2025-12-12..2026-01-10" in wb_adapter_step
    assert f"daily_sales_by_bundle={{{seeded['bundle_type'].id}: 2.0}}" in wb_adapter_step
    assert f"wb_stock_by_bundle={{{seeded['bundle_type'].id}: 20}}" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: '{stock_updated_at.strftime('%Y-%m-%dT%H:%M:%S')}" in wb_adapter_step
    assert "freshness_status=" in wb_adapter_step
    assert "freshness_sales_age_days=" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step
    assert "freshness_threshold_days=sales:3|stock:2" in wb_adapter_step
    assert "bundle_stock=request" in source_step
    assert "ready stock наборов (WB+локальный)=20" in stock_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    assert from_wb_meta["observation_window_days"] == 30
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] == "2026-01-10"
    assert from_wb_meta["as_of_date"] == "2026-01-10"
    assert from_wb_meta["as_of_source"] == "request"
    assert from_wb_meta["sales_window"] == {
        "start_date": "2025-12-12",
        "end_date": "2026-01-10",
    }
    assert from_wb_meta["bundle_type_ids"] == [seeded["bundle_type"].id]
    bundle_key = str(seeded["bundle_type"].id)
    assert from_wb_meta["daily_sales_by_bundle"][bundle_key] == 2.0
    assert from_wb_meta["wb_stock_by_bundle"][bundle_key] == 20
    assert from_wb_meta["wb_stock_updated_at_by_bundle"][bundle_key].startswith("2026-01-11T")
    assert from_wb_meta["freshness"]["status"] in {"fresh", "stale"}
    assert from_wb_meta["freshness"]["threshold_days"] == {"sales": 3, "stock": 2}
    assert from_wb_meta["freshness"]["threshold_source"] == {
        "sales": "global_default",
        "stock": "global_default",
    }


def test_production_order_proposal_from_wb_uses_latest_sales_as_of_when_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 9, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-LATEST",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-LATEST",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-LATEST",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )

    assert "requested_as_of_date=none" in wb_adapter_step
    assert "freshness_mode=warn" in wb_adapter_step
    assert "as_of_date=2026-01-10" in wb_adapter_step
    assert "as_of_source=latest_sales" in wb_adapter_step
    assert "sales_window=2025-12-12..2026-01-10" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: '{stock_updated_at.strftime('%Y-%m-%dT%H:%M:%S')}" in wb_adapter_step
    assert "freshness_status=" in wb_adapter_step
    assert "freshness_sales_age_days=" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] is None
    assert from_wb_meta["as_of_date"] == "2026-01-10"
    assert from_wb_meta["as_of_source"] == "latest_sales"
    assert from_wb_meta["sales_window"] == {
        "start_date": "2025-12-12",
        "end_date": "2026-01-10",
    }


def test_production_order_proposal_from_wb_without_sales_uses_none_as_of(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 8, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-NOSALES",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-NOSALES",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=7,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )

    assert "requested_as_of_date=none" in wb_adapter_step
    assert "freshness_mode=warn" in wb_adapter_step
    assert "as_of_date=none" in wb_adapter_step
    assert "as_of_source=none" in wb_adapter_step
    assert "sales_window=none" in wb_adapter_step
    assert f"daily_sales_by_bundle={{{seeded['bundle_type'].id}: 0.0}}" in wb_adapter_step
    assert f"wb_stock_by_bundle={{{seeded['bundle_type'].id}: 7}}" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: '{stock_updated_at.strftime('%Y-%m-%dT%H:%M:%S')}" in wb_adapter_step
    assert "freshness_status=" in wb_adapter_step
    assert "freshness_sales_age_days=none" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    bundle_key = str(seeded["bundle_type"].id)
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] is None
    assert from_wb_meta["as_of_date"] is None
    assert from_wb_meta["as_of_source"] == "none"
    assert from_wb_meta["sales_window"] is None
    assert from_wb_meta["daily_sales_by_bundle"][bundle_key] == 0.0
    assert from_wb_meta["wb_stock_by_bundle"][bundle_key] == 7
    assert from_wb_meta["freshness"]["sales_age_days"] is None


def test_production_order_proposal_from_wb_freshness_no_data_when_no_sales_and_no_stock(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-NODATA",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )

    assert "as_of_date=none" in wb_adapter_step
    assert "as_of_source=none" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: None" in wb_adapter_step
    assert "freshness_status=no_data" in wb_adapter_step
    assert "freshness_sales_age_days=none" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=none" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: None" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    bundle_key = str(seeded["bundle_type"].id)
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["as_of_date"] is None
    assert from_wb_meta["as_of_source"] == "none"
    assert from_wb_meta["sales_window"] is None
    assert from_wb_meta["wb_stock_updated_at_by_bundle"][bundle_key] is None
    assert from_wb_meta["freshness"]["status"] == "no_data"
    assert from_wb_meta["freshness"]["sales_age_days"] is None
    assert from_wb_meta["freshness"]["stock_oldest_age_days"] is None
    assert from_wb_meta["freshness"]["stock_age_days_by_bundle"][bundle_key] is None


def test_production_order_proposal_from_wb_clamps_future_as_of_date(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 7, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-FUTURE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-FUTURE",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-FUTURE",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-20",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )

    assert "requested_as_of_date=2026-01-20" in wb_adapter_step
    assert "freshness_mode=warn" in wb_adapter_step
    assert "as_of_date=2026-01-10" in wb_adapter_step
    assert "as_of_source=clamped_to_latest_sales" in wb_adapter_step
    assert "sales_window=2025-12-12..2026-01-10" in wb_adapter_step
    assert f"daily_sales_by_bundle={{{seeded['bundle_type'].id}: 2.0}}" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: '{stock_updated_at.strftime('%Y-%m-%dT%H:%M:%S')}" in wb_adapter_step
    assert "freshness_status=" in wb_adapter_step
    assert "freshness_sales_age_days=" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] == "2026-01-20"
    assert from_wb_meta["as_of_date"] == "2026-01-10"
    assert from_wb_meta["as_of_source"] == "clamped_to_latest_sales"
    assert from_wb_meta["sales_window"] == {
        "start_date": "2025-12-12",
        "end_date": "2026-01-10",
    }


def test_production_order_proposal_from_wb_via_import_endpoints(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    wb_sku = "WB-PO-INGEST-1"

    map_response = client.post(
        "/api/v1/wb/article-mapping/import",
        json={
            "items": [
                {
                    "article_id": seeded["article"].id,
                    "wb_sku": wb_sku,
                    "bundle_type_id": seeded["bundle_type"].id,
                    "size_id": seeded["size_s"].id,
                }
            ]
        },
    )
    assert map_response.status_code == 200, map_response.text

    sales_response = client.post(
        "/api/v1/wb/sales-daily/import",
        json={
            "items": [
                {
                    "wb_sku": wb_sku,
                    "date": "2026-01-15",
                    "sales_qty": 30,
                    "revenue": 1500.0,
                }
            ]
        },
    )
    assert sales_response.status_code == 200, sales_response.text

    stock_response = client.post(
        "/api/v1/wb/stock/import",
        json={
            "items": [
                {
                    "wb_sku": wb_sku,
                    "warehouse_id": 1,
                    "warehouse_name": "WB-1",
                    "stock_qty": 12,
                }
            ]
        },
    )
    assert stock_response.status_code == 200, stock_response.text

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-15",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    proposal_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload,
    )
    assert proposal_response.status_code == 200, proposal_response.text

    body = proposal_response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )
    source_step = next(
        (step for step in body["explanation"]["steps"] if "Источник параметров" in step),
        "",
    )
    stock_step = next(
        (step for step in body["explanation"]["steps"] if "ready stock наборов" in step),
        "",
    )

    assert "requested_as_of_date=2026-01-15" in wb_adapter_step
    assert "freshness_mode=warn" in wb_adapter_step
    assert "as_of_source=request" in wb_adapter_step
    assert "sales_window=2025-12-17..2026-01-15" in wb_adapter_step
    assert f"daily_sales_by_bundle={{{seeded['bundle_type'].id}: 1.0}}" in wb_adapter_step
    assert f"wb_stock_by_bundle={{{seeded['bundle_type'].id}: 12}}" in wb_adapter_step
    assert "wb_stock_updated_at_by_bundle={" in wb_adapter_step
    assert f"{seeded['bundle_type'].id}: '" in wb_adapter_step
    assert "freshness_status=" in wb_adapter_step
    assert "freshness_sales_age_days=" in wb_adapter_step
    assert "freshness_stock_oldest_age_days=" in wb_adapter_step
    assert "freshness_stock_age_days_by_bundle={" in wb_adapter_step
    assert "bundle_stock=request" in source_step
    assert "ready stock наборов (WB+локальный)=12" in stock_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    bundle_key = str(seeded["bundle_type"].id)
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] == "2026-01-15"
    assert from_wb_meta["as_of_date"] == "2026-01-15"
    assert from_wb_meta["as_of_source"] == "request"
    assert from_wb_meta["sales_window"] == {
        "start_date": "2025-12-17",
        "end_date": "2026-01-15",
    }
    assert from_wb_meta["daily_sales_by_bundle"][bundle_key] == 1.0
    assert from_wb_meta["wb_stock_by_bundle"][bundle_key] == 12
    assert from_wb_meta["wb_stock_updated_at_by_bundle"][bundle_key] is not None


def test_production_order_proposal_from_wb_strict_rejects_stale_data(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-STRICT-STALE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-STRICT-STALE",
            date=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-STRICT-STALE",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2020-01-01",
        "freshness_mode": "strict",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 400, response.text

    detail = response.json()["detail"]
    assert "WB data freshness check failed" in detail
    assert "status=stale" in detail


def test_production_order_proposal_from_wb_strict_rejects_no_data(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-STRICT-NODATA",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "freshness_mode": "strict",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 400, response.text

    detail = response.json()["detail"]
    assert "WB data freshness check failed" in detail
    assert "status=no_data" in detail


def test_production_order_proposal_from_wb_uses_admin_freshness_threshold_defaults(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-ADMIN-THRESHOLDS",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-ADMIN-THRESHOLDS",
            date=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-ADMIN-THRESHOLDS",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 3650,
            "freshness_stock_stale_after_days": 3650,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2020-01-01",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )
    assert "freshness_threshold_days=sales:3650|stock:3650" in wb_adapter_step
    assert "freshness_threshold_source=sales:admin_defaults|stock:admin_defaults" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    assert from_wb_meta["freshness"]["threshold_days"] == {"sales": 3650, "stock": 3650}
    assert from_wb_meta["freshness"]["threshold_source"] == {
        "sales": "admin_defaults",
        "stock": "admin_defaults",
    }


def test_production_order_proposal_from_wb_strict_with_custom_thresholds_allows_old_data(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-STRICT-OVERRIDE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-STRICT-OVERRIDE",
            date=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-STRICT-OVERRIDE",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=5,
            updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    settings_response = client.put(
        f"/api/v1/planning/core/production-order/settings/{seeded['article'].id}",
        json={
            "size_weights": [],
            "elastic_bindings": [],
            "in_flight_supply_defaults": [],
            "freshness_sales_stale_after_days": 1,
            "freshness_stock_stale_after_days": 1,
        },
    )
    assert settings_response.status_code == 200, settings_response.text

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2020-01-01",
        "freshness_mode": "strict",
        "freshness_sales_stale_after_days": 3650,
        "freshness_stock_stale_after_days": 3650,
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    wb_adapter_step = next(
        (step for step in body["explanation"]["steps"] if "WB ingestion adapter" in step),
        "",
    )
    assert "freshness_mode=strict" in wb_adapter_step
    assert "freshness_status=fresh" in wb_adapter_step
    assert "freshness_threshold_days=sales:3650|stock:3650" in wb_adapter_step
    assert "freshness_threshold_source=sales:request|stock:request" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    assert from_wb_meta["freshness_mode"] == "strict"
    assert from_wb_meta["freshness"]["status"] == "fresh"
    assert from_wb_meta["freshness"]["threshold_days"] == {
        "sales": 3650,
        "stock": 3650,
    }
    assert from_wb_meta["freshness"]["threshold_source"] == {
        "sales": "request",
        "stock": "request",
    }


def test_production_order_proposal_from_wb_rejects_article_without_bundle_types(client, db_session):
    article = Article(code="PO-NO-BT", name="PO-NO-BT")
    db_session.add(article)
    db_session.flush()
    db_session.add(
        GlobalPlanningSettings(
            default_target_coverage_days=60,
            default_lead_time_days=70,
            default_service_level_percent=90,
            default_fabric_min_batch_qty=7000,
            default_elastic_min_batch_qty=3000,
        )
    )
    db_session.commit()

    payload = {
        "article_id": article.id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "in_flight_supply": [],
        "size_weights": {},
        "bundle_type_ids": [],
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "No WB-mapped bundle types found for the article"


def test_production_order_proposal_from_wb_rejects_unmapped_requested_bundle_type(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        f"Missing WB mapping for bundle_type_id(s): [{seeded['bundle_type'].id}]"
    )


def test_production_order_proposal_from_wb_validation_error_invalid_freshness_mode(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": 1,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "freshness_mode": "hard_fail",
            "bundle_type_ids": [1],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 422, response.text


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
