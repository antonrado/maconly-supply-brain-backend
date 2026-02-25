from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.services.planning_production_order import (
    ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE,
    ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE,
    ASSORTI_CLASSIFICATION_SOURCE,
    EXPLAINABILITY_MODE_COMPACT,
    LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD,
    LAYER2_ALLOCATION_METHOD,
    LAYER2_CONTRACT_VERSION,
    LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD,
    LAYER3_CONTRACT_VERSION,
    LAYER4_SCENARIO_FACTORS,
    LAYER5_CONTRACT_VERSION,
    LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    LAYER_PROXY_VALUE_SOURCE,
    LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
    _apply_layer3_purchase_shaping,
    _build_layer1_stock_health_metrics,
    _build_layer1_contract_summary,
    _build_layer2_allocation_decisions,
    _build_layer2_contract_summary,
    _build_layer2_decision_quality_summary,
    _build_layer3_contract_summary,
    _build_layer4_scenarios,
    _build_layer4_contract_summary,
    _build_layer5_contract_summary,
    _build_layer5_intervention_signals,
    _choose_action,
)
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


def test_layer2_contract_summary_marks_violated_for_tie_break_and_summary_mismatch():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 0.8,
            "profit_if_assorti_until_eta": 0.8,
            "profit_gap_until_eta": 0.3,
            "capital_locked": -1.0,
            "gmroi_main": 0.1,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.2,
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": False,
        },
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 0,
            "profit_if_main_until_eta": -0.1,
            "profit_if_assorti_until_eta": 0.2,
            "profit_gap_until_eta": 0.1,
            "capital_locked": "invalid",
            "gmroi_main": -0.3,
            "gmroi_assorti": 0.1,
            "gmroi_gap": "invalid",
            "allocation_decision": "invalid",
            "decision_reason": "profit_tie_hold",
            "tie_break_applied": "yes",
            "near_tie": "yes",
        },
    ]
    summary = {"main": 0, "assorti": 0, "hold": 1}

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary=summary,
    )

    assert contract["version"] == LAYER2_CONTRACT_VERSION
    assert contract["status"] == "violated"
    assert contract["decision_count"] == 2
    assert contract["summary_expected"] == {"main": 0, "assorti": 0, "hold": 1}
    assert contract["summary_actual"] == {"main": 1, "assorti": 0, "hold": 0}
    assert contract["checks"] == {
        "summary_matches_decisions": False,
        "summary_total_matches_decision_count": False,
        "valid_decisions_only": False,
        "unique_color_size_pairs": False,
        "non_negative_profit_metrics": False,
        "non_negative_gmroi_metrics": False,
        "eta_days_positive": False,
        "tie_break_hold_when_equal_profit": False,
        "decision_reason_matches_allocation": False,
        "allocation_matches_profit_gate": False,
        "tie_break_applied_matches_profit_tie": False,
        "near_tie_matches_profit_gap_threshold": False,
        "profit_gap_consistent_with_profits": False,
        "gmroi_gap_consistent_with_gmroi": False,
        "capital_locked_metric_valid": False,
    }


def test_layer2_allocation_rounding_boundary_stays_contract_consistent():
    metrics = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "current_stock": 10,
            "in_flight": 0,
            "velocity_main": 1.00004,
            "velocity_assorti": 1.1764705882352942,
            "capital_locked": 10.0,
            "stockout_risk": 0.0,
            "overstock_risk": 0.0,
        }
    ]

    decisions, summary = _build_layer2_allocation_decisions(
        stock_health_metrics=metrics,
        lead_time_days_total=30,
    )

    assert summary == {"main": 0, "assorti": 0, "hold": 1}
    assert decisions == [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 1.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 0.0,
            "capital_locked": 10.0,
            "gmroi_main": 0.1,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.0,
            "allocation_decision": "hold",
            "decision_reason": "profit_tie_hold",
            "tie_break_applied": True,
            "near_tie": True,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary=summary,
    )

    assert contract["status"] == "ok"
    assert contract["checks"]["tie_break_hold_when_equal_profit"] is True
    assert contract["checks"]["allocation_matches_profit_gate"] is True
    assert contract["checks"]["tie_break_applied_matches_profit_tie"] is True
    assert contract["checks"]["near_tie_matches_profit_gap_threshold"] is True


def test_layer2_contract_summary_marks_violated_when_allocation_conflicts_with_profit_gate():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 2.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 1.0,
            "capital_locked": 10.0,
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "assorti",
            "decision_reason": "profit_assorti_gt_main",
            "tie_break_applied": False,
            "near_tie": True,
        }
    ]
    summary = {"main": 0, "assorti": 1, "hold": 0}

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary=summary,
    )

    assert contract["status"] == "violated"
    assert contract["checks"]["decision_reason_matches_allocation"] is True
    assert contract["checks"]["allocation_matches_profit_gate"] is False


def test_layer2_decision_quality_summary_tracks_ties_near_ties_and_reason_counts():
    decisions = [
        {
            "profit_if_main_until_eta": 2.5,
            "profit_if_assorti_until_eta": 2.3,
            "gmroi_main": 0.40,
            "gmroi_assorti": 0.36,
            "capital_locked": 10.0,
            "decision_reason": "profit_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": True,
        },
        {
            "profit_if_main_until_eta": 1.2,
            "profit_if_assorti_until_eta": 1.2,
            "gmroi_main": 0.20,
            "gmroi_assorti": 0.20,
            "capital_locked": 10.0,
            "decision_reason": "profit_tie_hold",
            "tie_break_applied": True,
            "near_tie": True,
        },
        {
            "profit_if_main_until_eta": 1.0,
            "profit_if_assorti_until_eta": 3.0,
            "gmroi_main": 0.10,
            "gmroi_assorti": 0.30,
            "capital_locked": 10.0,
            "decision_reason": "profit_assorti_gt_main",
            "tie_break_applied": False,
            "near_tie": False,
        },
    ]

    summary = _build_layer2_decision_quality_summary(
        layer2_allocation_decisions=decisions,
        near_tie_profit_gap_threshold=0.5,
    )

    assert summary == {
        "profit_gate_primary": True,
        "gmroi_usage": "diagnostic_only",
        "near_tie_profit_gap_threshold": 0.5,
        "decision_count": 3,
        "tie_count": 1,
        "near_tie_count": 2,
        "decision_reason_counts": {
            "profit_main_gt_assorti": 1,
            "profit_assorti_gt_main": 1,
            "profit_tie_hold": 1,
        },
        "avg_profit_gap_until_eta": 0.7333,
        "avg_gmroi_gap": 0.08,
        "capital_locked_total": 30.0,
        "capital_locked_avg": 10.0,
    }


def test_layer3_contract_summary_marks_violated_for_invariant_breaks():
    contract = _build_layer3_contract_summary(
        {
            "qty_before": 12,
            "qty_after_base": 7,
            "qty_after": 9,
            "qty_delta_vs_base": 1,
            "adjusted_lines": 5,
            "main_lines": 2,
            "assorti_lines": 1,
            "hold_lines": 0,
            "calibration": {
                "method": "unexpected_method",
                "risk_lines_covered": 2,
                "risk_lines_missing": 0,
                "up_lines": 2,
                "down_lines": 2,
                "factor_bounds": {
                    "main": {
                        "min": 0.7,
                        "max": 1.2,
                    }
                },
                "factor_summary": {
                    "avg": 0.5,
                    "min": 0.6,
                    "max": 2.0,
                },
            },
        }
    )

    assert contract == {
        "version": LAYER3_CONTRACT_VERSION,
        "status": "violated",
        "decision_lines": 3,
        "checks": {
            "non_negative_quantities": True,
            "qty_delta_matches_after_minus_base": False,
            "non_negative_line_counts": True,
            "adjusted_lines_within_decision_lines": False,
            "non_negative_risk_line_counts": True,
            "risk_partition_matches_decision_lines": False,
            "non_negative_calibration_direction_counts": True,
            "calibration_direction_counts_within_decision_lines": False,
            "calibration_method_matches": False,
            "factor_bounds_match_expected": False,
            "factor_summary_consistent": False,
            "factor_summary_within_bounds": False,
        },
    }


def test_layer5_contract_summary_marks_violated_for_threshold_and_signal_invariants():
    contract = _build_layer5_contract_summary(
        layer5_intervention={
            "method": "unexpected",
            "signal_policy": "unexpected_policy",
            "unavoidable_stockout": "yes",
            "signals": [
                "accelerate_production",
                "increase_price_to_slow_velocity",
                "accelerate_production",
            ],
            "reason": "none",
            "aggressive_stockout_risk_proxy": -0.2,
            "risk_threshold": 0.31,
            "signal_thresholds": {
                "accelerate_production": 0.2,
                "increase_price_to_slow_velocity": 1.2,
            },
        },
        unavoidable_stockout_risk_threshold=LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        accelerate_production_risk_threshold=LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    )

    assert contract == {
        "version": LAYER5_CONTRACT_VERSION,
        "status": "violated",
        "signal_count": 3,
        "checks": {
            "method_matches_expected": False,
            "signal_policy_matches_expected": False,
            "unavoidable_stockout_is_bool": False,
            "aggressive_risk_in_unit_interval": False,
            "thresholds_in_unit_interval": False,
            "threshold_sources_match_effective": False,
            "threshold_order_valid": False,
            "risk_threshold_matches_price_slowdown_threshold": False,
            "signals_known_only": True,
            "signals_unique": False,
            "signals_order_is_canonical": False,
            "non_unavoidable_has_no_signals_and_none_reason": False,
            "unavoidable_has_signals": True,
            "reason_consistent_with_signals": False,
            "accelerate_signal_requires_severe_risk": False,
            "price_slowdown_signal_requires_unavoidable_threshold": False,
        },
    }


def _business_projection(body: dict[str, object]) -> dict[str, object]:
    return {
        "status": body["status"],
        "article_id": body["article_id"],
        "risk_level": body["risk_level"],
        "days_of_cover_estimate": body["days_of_cover_estimate"],
        "lead_time_days_total": body["lead_time_days_total"],
        "reorder_point_days": body.get("reorder_point_days"),
        "recommendation": body["recommendation"],
        "alternatives": body["alternatives"],
        "constraints_applied": body["constraints_applied"],
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


def test_production_order_proposal_compact_explainability_mode(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    steps = body["explanation"]["steps"]
    assert any("Layer 1 stock health" in step for step in steps)
    assert any("Layer 2 allocation" in step for step in steps)
    assert any("Layer 5 intervention" in step for step in steps)
    assert any("Explainability compact mode: omitted_steps=" in step for step in steps)
    layer2_step = next((step for step in steps if "Layer 2 allocation" in step), "")
    assert "decision_gate=profit_until_eta" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step

    meta = body["explanation"]["meta"]
    assert meta["explainability"]["mode"] == EXPLAINABILITY_MODE_COMPACT
    assert meta["explainability"]["steps_omitted"] >= 1
    assert "metrics" not in meta["layer_1_stock_health"]
    assert meta["layer_1_stock_health"]["contract"]["status"] == "ok"
    assert "bundle_types" not in meta["layer_1_stock_health"]["assorti_classification"]
    assert "decisions" not in meta["layer_2_allocation"]
    assert meta["layer_2_allocation"]["contract"]["status"] == "ok"
    layer2_compact_contract_checks = meta["layer_2_allocation"]["contract"]["checks"]
    assert layer2_compact_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_compact_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_compact_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_compact_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_compact_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_compact_contract_checks["capital_locked_metric_valid"] is True
    assert meta["layer_2_allocation"]["decision_quality"]["profit_gate_primary"] is True
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert meta["layer_3_purchase_shaping"]["contract"]["status"] == "ok"
    assert meta["layer_4_scenarios"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_policy"] == "critical_risk_thresholds"
    assert meta["layer_5_intervention"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["layer_3_calibration"]["method"] == "risk_weighted_factor_clamp"
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }
    assert "line_keys" not in meta["elastic_uplift"]
    assert "line_alloc" not in meta["elastic_uplift"]


def test_production_order_proposal_compact_mode_preserves_deterministic_output(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    full_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert full_response.status_code == 200, full_response.text

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    full_body = full_response.json()
    compact_body = compact_response.json()
    assert _business_projection(full_body) == _business_projection(compact_body)

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert "decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True


@pytest.mark.parametrize(
    ("profile_name", "daily_sales", "bundle_stock_total"),
    [
        pytest.param("stockout", 20.0, 10, id="stockout"),
        pytest.param("balanced", 8.0, 120, id="balanced"),
        pytest.param("overstock", 2.0, 1500, id="overstock"),
    ],
)
def test_production_order_proposal_compact_mode_preserves_deterministic_output_across_profiles(
    client,
    db_session,
    profile_name,
    daily_sales,
    bundle_stock_total,
):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"] = [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "daily_sales": daily_sales,
        }
    ]
    payload["bundle_stock"] = [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "wb_qty": bundle_stock_total // 2,
            "local_qty": bundle_stock_total - (bundle_stock_total // 2),
        }
    ]
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0
    payload["overrides"]["allow_order_with_buffer"] = False

    full_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload,
    )
    assert full_response.status_code == 200, full_response.text

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    full_body = full_response.json()
    compact_body = compact_response.json()
    assert _business_projection(full_body) == _business_projection(compact_body)

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert "decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    if profile_name == "overstock":
        assert compact_body["risk_level"] == "overstock"


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


def test_production_order_proposal_exposes_layer1_layer2_layer3_layer4_layer5_meta(client, db_session):
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
    layer3 = meta["layer_3_purchase_shaping"]
    layer4 = meta["layer_4_scenarios"]
    layer5 = meta["layer_5_intervention"]

    assert layer1["summary"]["sku_count"] == 4
    assert layer1["summary"]["high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
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
    assert layer1["contract"] == {
        "version": "v1_alpha",
        "status": "ok",
        "sku_count": 4,
        "checks": {
            "unique_color_size_pairs": True,
            "risk_bounds_valid": True,
            "non_negative_quantities": True,
            "non_negative_velocity": True,
            "non_negative_coverage": True,
        },
    }
    assert layer1["assorti_classification"]["source"] == ASSORTI_CLASSIFICATION_SOURCE
    assert layer1["assorti_classification"]["source_breakdown"] == {
        ASSORTI_CLASSIFICATION_SOURCE: 1,
    }
    assert layer1["assorti_classification"]["summary"] == {
        "assorti_bundle_types": 0,
        "main_bundle_types": 1,
    }
    assert layer1["assorti_classification"]["bundle_types"] == [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "is_assorti": False,
            "source": ASSORTI_CLASSIFICATION_SOURCE,
        }
    ]

    assert layer2["method"] == LAYER2_ALLOCATION_METHOD
    assert layer2["decision_gate"] == "profit_until_eta"
    assert layer2["tie_break"] == "hold"
    assert layer2["gmroi_usage"] == "diagnostic_only"
    assert len(layer2["decisions"]) == 4
    assert layer2["summary"] == {"main": 4, "assorti": 0, "hold": 0}
    assert layer2["decision_quality"] == {
        "profit_gate_primary": True,
        "gmroi_usage": "diagnostic_only",
        "near_tie_profit_gap_threshold": LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD,
        "decision_count": 4,
        "tie_count": 0,
        "near_tie_count": 0,
        "decision_reason_counts": {
            "profit_main_gt_assorti": 4,
            "profit_assorti_gt_main": 0,
            "profit_tie_hold": 0,
        },
        "avg_profit_gap_until_eta": 10.0,
        "avg_gmroi_gap": 1.0,
        "capital_locked_total": 40.0,
        "capital_locked_avg": 10.0,
    }
    assert layer2["contract"] == {
        "version": LAYER2_CONTRACT_VERSION,
        "status": "ok",
        "decision_count": 4,
        "summary_expected": {"main": 4, "assorti": 0, "hold": 0},
        "summary_actual": {"main": 4, "assorti": 0, "hold": 0},
        "checks": {
            "summary_matches_decisions": True,
            "summary_total_matches_decision_count": True,
            "valid_decisions_only": True,
            "unique_color_size_pairs": True,
            "non_negative_profit_metrics": True,
            "non_negative_gmroi_metrics": True,
            "eta_days_positive": True,
            "tie_break_hold_when_equal_profit": True,
            "decision_reason_matches_allocation": True,
            "allocation_matches_profit_gate": True,
            "tie_break_applied_matches_profit_tie": True,
            "near_tie_matches_profit_gap_threshold": True,
            "profit_gap_consistent_with_profits": True,
            "gmroi_gap_consistent_with_gmroi": True,
            "capital_locked_metric_valid": True,
        },
    }

    assert layer3["method"] == "allocation_decision_factors"
    assert layer3["factors"] == {"main": 1.0, "assorti": 0.75, "hold": 0.35}
    assert layer3["main_lines"] == 4
    assert layer3["assorti_lines"] == 0
    assert layer3["hold_lines"] == 0
    assert layer3["qty_before"] >= layer3["qty_after_base"] >= 0
    assert layer3["qty_after"] >= 0
    assert layer3["qty_delta_vs_base"] == layer3["qty_after"] - layer3["qty_after_base"]
    assert layer3["calibration"]["stockout_boost_max"] == 0.3
    assert layer3["calibration"]["overstock_dampen_max"] == 0.4
    assert layer3["calibration"]["method"] == "risk_weighted_factor_clamp"
    assert layer3["calibration"]["risk_lines_covered"] + layer3["calibration"]["risk_lines_missing"] == (
        layer3["main_lines"] + layer3["assorti_lines"] + layer3["hold_lines"]
    )
    assert layer3["contract"] == {
        "version": LAYER3_CONTRACT_VERSION,
        "status": "ok",
        "decision_lines": 4,
        "checks": {
            "non_negative_quantities": True,
            "qty_delta_matches_after_minus_base": True,
            "non_negative_line_counts": True,
            "adjusted_lines_within_decision_lines": True,
            "non_negative_risk_line_counts": True,
            "risk_partition_matches_decision_lines": True,
            "non_negative_calibration_direction_counts": True,
            "calibration_direction_counts_within_decision_lines": True,
            "calibration_method_matches": True,
            "factor_bounds_match_expected": True,
            "factor_summary_consistent": True,
            "factor_summary_within_bounds": True,
        },
    }

    assert layer4["method"] == "deterministic_factor_scenarios"
    assert len(layer4["scenarios"]) == 3
    assert [item["scenario"] for item in layer4["scenarios"]] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert layer4["factors"] == [
        {
            "scenario": scenario,
            "factor": factor,
        }
        for scenario, factor in LAYER4_SCENARIO_FACTORS
    ]
    assert layer4["contract"]["version"] == "v1_alpha"
    assert layer4["contract"]["status"] == "ok"
    assert layer4["contract"]["order_matches_expected"] is True
    assert layer4["contract"]["scenario_order_expected"] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert layer4["contract"]["scenario_order_actual"] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert layer4["contract"]["checks"] == {
        "capital_non_decreasing": True,
        "stockout_risk_non_increasing": True,
        "turnover_non_increasing": True,
        "purchase_units_non_decreasing": True,
    }

    conservative = layer4["scenarios"][0]
    balanced = layer4["scenarios"][1]
    aggressive = layer4["scenarios"][2]
    assert conservative["total_capital_required"] < balanced["total_capital_required"] < aggressive["total_capital_required"]
    assert conservative["stockout_risk_proxy"] >= balanced["stockout_risk_proxy"] >= aggressive["stockout_risk_proxy"]
    assert conservative["assorti_sustainability_impact"] == "neutral_no_assorti_signal"
    assert balanced["assorti_sustainability_impact"] == "neutral_no_assorti_signal"
    assert aggressive["assorti_sustainability_impact"] == "neutral_no_assorti_signal"

    assert layer5["method"] == "deterministic_unavoidable_stockout_flags"
    assert layer5["signal_policy"] == "critical_risk_thresholds"
    assert layer5["risk_threshold"] == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    assert layer5["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }
    assert layer5["contract"] == {
        "version": LAYER5_CONTRACT_VERSION,
        "status": "ok",
        "signal_count": len(layer5["signals"]),
        "checks": {
            "method_matches_expected": True,
            "signal_policy_matches_expected": True,
            "unavoidable_stockout_is_bool": True,
            "aggressive_risk_in_unit_interval": True,
            "thresholds_in_unit_interval": True,
            "threshold_sources_match_effective": True,
            "threshold_order_valid": True,
            "risk_threshold_matches_price_slowdown_threshold": True,
            "signals_known_only": True,
            "signals_unique": True,
            "signals_order_is_canonical": True,
            "non_unavoidable_has_no_signals_and_none_reason": True,
            "unavoidable_has_signals": True,
            "reason_consistent_with_signals": True,
            "accelerate_signal_requires_severe_risk": True,
            "price_slowdown_signal_requires_unavoidable_threshold": True,
        },
    }
    assert isinstance(layer5["unavoidable_stockout"], bool)
    assert isinstance(layer5["signals"], list)
    assert layer5["reason"] in {
        "none",
        "no_effective_in_flight_and_high_stockout_risk",
        "no_effective_in_flight_but_stockout_risk_persists",
        "in_flight_present_but_stockout_risk_persists",
        "in_flight_present_but_severe_stockout_risk",
    }

    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["source"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["calibration_state"] == "alpha_proxy_not_calibrated"
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert alpha_proxy["layer_2_allocation_method"] == LAYER2_ALLOCATION_METHOD
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["margin_proxy"] == {"main": 1.0, "assorti": 0.85}
    assert alpha_proxy["unit_capital_proxy"] == 1.0
    assert alpha_proxy["layer_3_purchase_factors"] == {
        "main": 1.0,
        "assorti": 0.75,
        "hold": 0.35,
    }
    assert alpha_proxy["layer_3_calibration"] == {
        "method": "risk_weighted_factor_clamp",
        "stockout_boost_max": 0.3,
        "overstock_dampen_max": 0.4,
        "stockout_weight_by_decision": {
            "main": 1.0,
            "assorti": 0.7,
            "hold": 0.15,
        },
        "overstock_weight_by_decision": {
            "main": 0.35,
            "assorti": 0.6,
            "hold": 1.0,
        },
        "factor_bounds": {
            "main": {
                "min": 0.65,
                "max": 1.25,
            },
            "assorti": {
                "min": 0.3,
                "max": 0.95,
            },
            "hold": {
                "min": 0.1,
                "max": 0.6,
            },
        },
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": LAYER_PROXY_VALUE_SOURCE,
        "layer3_overstock_dampen_max": LAYER_PROXY_VALUE_SOURCE,
        "layer5_unavoidable_stockout_risk_threshold": LAYER_PROXY_VALUE_SOURCE,
        "layer5_accelerate_production_risk_threshold": LAYER_PROXY_VALUE_SOURCE,
    }
    assert alpha_proxy["layer5_threshold_order_adjusted"] is False
    assert alpha_proxy["layer_4_scenario_factors"] == layer4["factors"]
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert (
        alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }

    layer1_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 1 stock health" in step),
        "",
    )
    assorti_step = next(
        (step for step in body["explanation"]["steps"] if "Assorti classification" in step),
        "",
    )
    layer2_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    layer3_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 3 purchase shaping" in step),
        "",
    )
    layer4_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 4 scenarios" in step),
        "",
    )
    layer4_contract_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 4 contract" in step),
        "",
    )
    layer5_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 5 intervention" in step),
        "",
    )
    assert "sku_count=4" in layer1_step
    assert f"high_stockout_threshold={LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD}" in layer1_step
    assert "contract_status=ok" in layer1_step
    assert f"source={ASSORTI_CLASSIFICATION_SOURCE}" in assorti_step
    assert "assorti_bundle_types=0" in assorti_step
    assert "main_bundle_types=1" in assorti_step
    assert "main=4" in layer2_step
    assert f"method={LAYER2_ALLOCATION_METHOD}" in layer2_step
    assert "decision_gate=profit_until_eta" in layer2_step
    assert "tie_break=hold" in layer2_step
    assert "near_tie=0" in layer2_step
    assert "tie_count=0" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step
    assert "main:4|assorti:0|hold:0" in layer3_step
    assert "contract_status=ok" in layer3_step
    assert "Conservative(capital=" in layer4_step
    assert "Aggressive(capital=" in layer4_step
    assert "status=ok" in layer4_contract_step
    assert "order_matches_expected=True" in layer4_contract_step
    assert "unavoidable_stockout=" in layer5_step
    assert "signals=" in layer5_step
    assert "contract_status=ok" in layer5_step

    if body["recommendation"] is not None and body["recommendation"]["lines"]:
        assert all(
            "|layer2:main" in line["source_reason"]
            for line in body["recommendation"]["lines"]
        )


def test_production_order_proposal_layer3_shaping_reduces_qty_for_explicit_assorti_flag(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-MIX-EXPLICIT",
        name="PO-BT-MIX-EXPLICIT",
        is_assorti=True,
    )
    db_session.add(assorti_bundle_type)
    db_session.flush()

    db_session.add_all(
        [
            BundleRecipe(
                article_id=seeded["article"].id,
                bundle_type_id=assorti_bundle_type.id,
                color_id=seeded["color_1"].id,
                position=1,
            ),
            BundleRecipe(
                article_id=seeded["article"].id,
                bundle_type_id=assorti_bundle_type.id,
                color_id=seeded["color_2"].id,
                position=2,
            ),
        ]
    )
    db_session.commit()

    payload_main = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload_main["overrides"]["fabric_min_batch_qty_default"] = 0
    payload_main["overrides"]["elastic_min_batch_qty_default"] = 0

    payload_assorti = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=assorti_bundle_type.id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload_assorti["overrides"]["fabric_min_batch_qty_default"] = 0
    payload_assorti["overrides"]["elastic_min_batch_qty_default"] = 0

    response_main = client.post("/api/v1/planning/core/production-order/proposal", json=payload_main)
    response_assorti = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload_assorti,
    )

    assert response_main.status_code == 200, response_main.text
    assert response_assorti.status_code == 200, response_assorti.text

    body_main = response_main.json()
    body_assorti = response_assorti.json()

    assert body_main["recommendation"] is not None
    assert body_assorti["recommendation"] is not None
    assert body_main["recommendation"]["total_units"] > body_assorti["recommendation"]["total_units"]

    layer2_main = body_main["explanation"]["meta"]["layer_2_allocation"]["summary"]
    layer2_assorti = body_assorti["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assert layer2_main["main"] > 0
    assert layer2_main["assorti"] == 0
    assert layer2_assorti["assorti"] > 0
    assert layer2_assorti["main"] == 0

    assorti_classification_main = body_main["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assorti_classification_assorti = body_assorti["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assert assorti_classification_main["summary"] == {
        "assorti_bundle_types": 0,
        "main_bundle_types": 1,
    }
    assert assorti_classification_assorti["summary"] == {
        "assorti_bundle_types": 1,
        "main_bundle_types": 0,
    }
    assert assorti_classification_assorti["bundle_types"] == [
        {
            "bundle_type_id": assorti_bundle_type.id,
            "is_assorti": True,
            "source": ASSORTI_CLASSIFICATION_SOURCE,
        }
    ]

    layer3_main = body_main["explanation"]["meta"]["layer_3_purchase_shaping"]
    layer3_assorti = body_assorti["explanation"]["meta"]["layer_3_purchase_shaping"]
    assert layer3_main["main_lines"] > 0
    assert layer3_main["assorti_lines"] == 0
    assert layer3_assorti["assorti_lines"] > 0
    assert layer3_assorti["main_lines"] == 0
    assert layer3_main["qty_after"] > layer3_assorti["qty_after"]

    assert body_assorti["recommendation"]["lines"]
    assert all(
        "|layer2:assorti" in line["source_reason"]
        for line in body_assorti["recommendation"]["lines"]
    )

    layer4_assorti = body_assorti["explanation"]["meta"]["layer_4_scenarios"]["scenarios"]
    assert [item["scenario"] for item in layer4_assorti] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert layer4_assorti[0]["assorti_sustainability_impact"] == "negative"
    assert layer4_assorti[1]["assorti_sustainability_impact"] == "neutral"
    assert layer4_assorti[2]["assorti_sustainability_impact"] == "positive"


def test_production_order_proposal_assorti_classification_prefers_admin_fallback_over_global(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)
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
    assorti_classification = body["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assert assorti_classification["summary"] == {
        "assorti_bundle_types": 1,
        "main_bundle_types": 0,
    }
    assert assorti_classification["source_breakdown"] == {
        ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE: 1,
    }
    assert assorti_classification["bundle_types"] == [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "is_assorti": True,
            "source": ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE,
        }
    ]


def test_production_order_proposal_assorti_classification_uses_global_fallback_when_admin_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)
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
    assorti_classification = body["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assert assorti_classification["summary"] == {
        "assorti_bundle_types": 1,
        "main_bundle_types": 0,
    }
    assert assorti_classification["source_breakdown"] == {
        ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE: 1,
    }
    assert assorti_classification["bundle_types"] == [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "is_assorti": True,
            "source": ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE,
        }
    ]


def test_production_order_proposal_uses_global_layer_proxy_defaults_when_admin_and_request_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.19
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.11
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.29
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.39
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

    alpha_proxy = response.json()["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.19
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.11
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.29
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.39,
        "increase_price_to_slow_velocity": 0.29,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "global_default",
        "layer3_overstock_dampen_max": "global_default",
        "layer5_unavoidable_stockout_risk_threshold": "global_default",
        "layer5_accelerate_production_risk_threshold": "global_default",
    }


def test_production_order_proposal_request_layer_proxy_overrides_admin_and_global(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer3_stockout_boost_max = 0.17
    article_settings.production_order_layer3_overstock_dampen_max = 0.12
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.26
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.34

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.09
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.08
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.21
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.31
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0
    payload["overrides"]["layer3_stockout_boost_max"] = 0.23
    payload["overrides"]["layer3_overstock_dampen_max"] = 0.18
    payload["overrides"]["layer5_unavoidable_stockout_risk_threshold"] = 0.27
    payload["overrides"]["layer5_accelerate_production_risk_threshold"] = 0.41

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.23
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.18
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.27
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.41,
        "increase_price_to_slow_velocity": 0.27,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "request",
        "layer3_overstock_dampen_max": "request",
        "layer5_unavoidable_stockout_risk_threshold": "request",
        "layer5_accelerate_production_risk_threshold": "request",
    }

    layer3_calibration = body["explanation"]["meta"]["layer_3_purchase_shaping"]["calibration"]
    assert layer3_calibration["stockout_boost_max"] == 0.23
    assert layer3_calibration["overstock_dampen_max"] == 0.18
    assert body["explanation"]["meta"]["layer_5_intervention"]["risk_threshold"] == 0.27
    assert body["explanation"]["meta"]["layer_5_intervention"]["signal_thresholds"] == {
        "accelerate_production": 0.41,
        "increase_price_to_slow_velocity": 0.27,
    }


def test_production_order_proposal_layer3_calibration_changes_qty_but_not_layer2_decisions(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    base_payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    base_payload["overrides"]["fabric_min_batch_qty_default"] = 0
    base_payload["overrides"]["elastic_min_batch_qty_default"] = 0
    base_payload["overrides"]["allow_order_with_buffer"] = False

    low_calibration_payload = deepcopy(base_payload)
    low_calibration_payload["overrides"]["layer3_stockout_boost_max"] = 0.0
    low_calibration_payload["overrides"]["layer3_overstock_dampen_max"] = 0.0

    high_calibration_payload = deepcopy(base_payload)
    high_calibration_payload["overrides"]["layer3_stockout_boost_max"] = 1.0
    high_calibration_payload["overrides"]["layer3_overstock_dampen_max"] = 0.0

    low_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=low_calibration_payload,
    )
    assert low_response.status_code == 200, low_response.text

    high_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=high_calibration_payload,
    )
    assert high_response.status_code == 200, high_response.text

    low_body = low_response.json()
    high_body = high_response.json()

    low_layer2 = low_body["explanation"]["meta"]["layer_2_allocation"]
    high_layer2 = high_body["explanation"]["meta"]["layer_2_allocation"]

    assert low_layer2["summary"] == high_layer2["summary"]
    assert low_layer2["decisions"] == high_layer2["decisions"]
    assert low_layer2["contract"]["status"] == "ok"
    assert high_layer2["contract"]["status"] == "ok"

    low_layer3 = low_body["explanation"]["meta"]["layer_3_purchase_shaping"]
    high_layer3 = high_body["explanation"]["meta"]["layer_3_purchase_shaping"]

    assert low_layer3["calibration"]["stockout_boost_max"] == 0.0
    assert high_layer3["calibration"]["stockout_boost_max"] == 1.0
    assert low_layer3["calibration"]["overstock_dampen_max"] == 0.0
    assert high_layer3["calibration"]["overstock_dampen_max"] == 0.0

    assert high_layer3["qty_after"] > low_layer3["qty_after"]
    assert high_body["recommendation"]["total_units"] > low_body["recommendation"]["total_units"]


def test_production_order_proposal_layer5_signals_do_not_override_recommendation_action(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    base_payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    base_payload["overrides"]["fabric_min_batch_qty_default"] = 0
    base_payload["overrides"]["elastic_min_batch_qty_default"] = 0
    base_payload["overrides"]["allow_order_with_buffer"] = False

    low_threshold_payload = deepcopy(base_payload)
    low_threshold_payload["overrides"]["layer5_unavoidable_stockout_risk_threshold"] = 0.0
    low_threshold_payload["overrides"]["layer5_accelerate_production_risk_threshold"] = 0.0

    high_threshold_payload = deepcopy(base_payload)
    high_threshold_payload["overrides"]["layer5_unavoidable_stockout_risk_threshold"] = 1.0
    high_threshold_payload["overrides"]["layer5_accelerate_production_risk_threshold"] = 1.0

    low_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=low_threshold_payload,
    )
    assert low_response.status_code == 200, low_response.text

    high_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=high_threshold_payload,
    )
    assert high_response.status_code == 200, high_response.text

    low_body = low_response.json()
    high_body = high_response.json()

    assert _business_projection(low_body) == _business_projection(high_body)
    assert low_body["recommendation"]["action"] == "order_minimum_only"
    assert high_body["recommendation"]["action"] == "order_minimum_only"

    low_layer5 = low_body["explanation"]["meta"]["layer_5_intervention"]
    high_layer5 = high_body["explanation"]["meta"]["layer_5_intervention"]

    assert low_layer5["signals"] == ["accelerate_production"]
    assert low_layer5["reason"] == "no_effective_in_flight_and_high_stockout_risk"
    assert high_layer5["signals"] == []
    assert high_layer5["reason"] == "none"


def test_production_order_proposal_layer5_threshold_order_is_clamped_when_admin_invalid(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.44
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.21
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

    alpha_proxy = response.json()["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer5_threshold_order_adjusted"] is True
    assert alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "admin_defaults"
    assert (
        alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"]
        == "admin_defaults|clamped_to_unavoidable"
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.44,
        "increase_price_to_slow_velocity": 0.44,
    }


def test_layer3_purchase_shaping_calibration_boosts_and_dampens_by_risk():
    line_qty = {
        (10, 1): 100,
        (10, 2): 100,
        (10, 3): 100,
    }
    layer2_decisions = [
        {
            "color_id": 10,
            "size_id": 1,
            "allocation_decision": "main",
        },
        {
            "color_id": 10,
            "size_id": 2,
            "allocation_decision": "assorti",
        },
        {
            "color_id": 10,
            "size_id": 3,
            "allocation_decision": "hold",
        },
    ]
    layer1_metrics = [
        {
            "color_id": 10,
            "size_id": 1,
            "stockout_risk": 1.0,
            "overstock_risk": 0.0,
        },
        {
            "color_id": 10,
            "size_id": 2,
            "stockout_risk": 0.0,
            "overstock_risk": 1.0,
        },
        {
            "color_id": 10,
            "size_id": 3,
            "stockout_risk": 0.0,
            "overstock_risk": 1.0,
        },
    ]

    decision_by_line, shaping = _apply_layer3_purchase_shaping(
        line_qty=line_qty,
        layer2_allocation_decisions=layer2_decisions,
        layer1_stock_health_metrics=layer1_metrics,
    )

    assert decision_by_line == {
        (10, 1): "main",
        (10, 2): "assorti",
        (10, 3): "hold",
    }
    assert line_qty == {
        (10, 1): 125,
        (10, 2): 51,
        (10, 3): 10,
    }

    assert shaping["qty_before"] == 300
    assert shaping["qty_after_base"] == 210
    assert shaping["qty_after"] == 186
    assert shaping["qty_delta_vs_base"] == -24
    assert shaping["main_lines"] == 1
    assert shaping["assorti_lines"] == 1
    assert shaping["hold_lines"] == 1
    assert shaping["calibration_up_lines"] == 1
    assert shaping["calibration_down_lines"] == 2

    calibration = shaping["calibration"]
    assert calibration["method"] == "risk_weighted_factor_clamp"
    assert calibration["risk_lines_covered"] == 3
    assert calibration["risk_lines_missing"] == 0
    assert calibration["up_lines"] == 1
    assert calibration["down_lines"] == 2
    assert calibration["factor_summary"] == {
        "avg": 0.62,
        "min": 0.1,
        "max": 1.25,
    }


def test_layer1_contract_summary_marks_violations_for_duplicate_and_invalid_risk():
    metrics = [
        {
            "color_id": 7,
            "size_id": 8,
            "velocity_main": 1.0,
            "velocity_assorti": 0.0,
            "coverage_days": 3.0,
            "current_stock": 3,
            "in_flight": 0,
            "capital_locked": 3.0,
            "stockout_risk": 1.2,
            "overstock_risk": 0.0,
        },
        {
            "color_id": 7,
            "size_id": 8,
            "velocity_main": -0.1,
            "velocity_assorti": 0.0,
            "coverage_days": -1.0,
            "current_stock": -1,
            "in_flight": 0,
            "capital_locked": -1.0,
            "stockout_risk": 0.1,
            "overstock_risk": 0.2,
        },
    ]

    contract = _build_layer1_contract_summary(metrics)

    assert contract == {
        "version": "v1_alpha",
        "status": "violated",
        "sku_count": 2,
        "checks": {
            "unique_color_size_pairs": False,
            "risk_bounds_valid": False,
            "non_negative_quantities": False,
            "non_negative_velocity": False,
            "non_negative_coverage": False,
        },
    }


def test_layer4_contract_summary_marks_violated_when_order_and_monotonicity_break():
    scenarios = [
        {
            "scenario": "Balanced",
            "total_capital_required": 100.0,
            "expected_turnover_proxy": 0.3,
            "stockout_risk_proxy": 0.20,
            "purchase_units": 100,
        },
        {
            "scenario": "Conservative",
            "total_capital_required": 90.0,
            "expected_turnover_proxy": 0.4,
            "stockout_risk_proxy": 0.25,
            "purchase_units": 90,
        },
        {
            "scenario": "Aggressive",
            "total_capital_required": 80.0,
            "expected_turnover_proxy": 0.35,
            "stockout_risk_proxy": 0.30,
            "purchase_units": 80,
        },
    ]

    contract = _build_layer4_contract_summary(scenarios)

    assert contract == {
        "version": "v1_alpha",
        "status": "violated",
        "order_matches_expected": False,
        "scenario_order_expected": ["Conservative", "Balanced", "Aggressive"],
        "scenario_order_actual": ["Balanced", "Conservative", "Aggressive"],
        "checks": {
            "capital_non_decreasing": False,
            "stockout_risk_non_increasing": False,
            "turnover_non_increasing": False,
            "purchase_units_non_decreasing": False,
        },
    }


def test_layer5_intervention_signals_accelerate_when_no_in_flight():
    scenarios = [
        {"scenario": "Conservative", "stockout_risk_proxy": 0.70},
        {"scenario": "Balanced", "stockout_risk_proxy": 0.60},
        {"scenario": "Aggressive", "stockout_risk_proxy": 0.40},
    ]

    result = _build_layer5_intervention_signals(
        risk_level="critical",
        layer4_scenarios=scenarios,
        in_flight_effective_qty_total=0,
    )

    assert result == {
        "method": "deterministic_unavoidable_stockout_flags",
        "signal_policy": "critical_risk_thresholds",
        "unavoidable_stockout": True,
        "signals": ["accelerate_production"],
        "reason": "no_effective_in_flight_and_high_stockout_risk",
        "aggressive_stockout_risk_proxy": 0.4,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        },
    }


def test_layer5_intervention_signals_dual_signal_when_severe_and_in_flight_present():
    scenarios = [
        {"scenario": "Conservative", "stockout_risk_proxy": 0.70},
        {"scenario": "Balanced", "stockout_risk_proxy": 0.60},
        {"scenario": "Aggressive", "stockout_risk_proxy": 0.45},
    ]

    result = _build_layer5_intervention_signals(
        risk_level="critical",
        layer4_scenarios=scenarios,
        in_flight_effective_qty_total=50,
    )

    assert result == {
        "method": "deterministic_unavoidable_stockout_flags",
        "signal_policy": "critical_risk_thresholds",
        "unavoidable_stockout": True,
        "signals": [
            "accelerate_production",
            "increase_price_to_slow_velocity",
        ],
        "reason": "in_flight_present_but_severe_stockout_risk",
        "aggressive_stockout_risk_proxy": 0.45,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        },
    }


def test_layer5_intervention_signals_price_slowdown_when_in_flight_present():
    scenarios = [
        {"scenario": "Conservative", "stockout_risk_proxy": 0.70},
        {"scenario": "Balanced", "stockout_risk_proxy": 0.60},
        {"scenario": "Aggressive", "stockout_risk_proxy": 0.31},
    ]

    result = _build_layer5_intervention_signals(
        risk_level="critical",
        layer4_scenarios=scenarios,
        in_flight_effective_qty_total=50,
    )

    assert result == {
        "method": "deterministic_unavoidable_stockout_flags",
        "signal_policy": "critical_risk_thresholds",
        "unavoidable_stockout": True,
        "signals": ["increase_price_to_slow_velocity"],
        "reason": "in_flight_present_but_stockout_risk_persists",
        "aggressive_stockout_risk_proxy": 0.31,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        },
    }


def test_layer5_intervention_signals_not_triggered_when_not_unavoidable():
    scenarios = [
        {"scenario": "Conservative", "stockout_risk_proxy": 0.20},
        {"scenario": "Balanced", "stockout_risk_proxy": 0.10},
        {"scenario": "Aggressive", "stockout_risk_proxy": 0.05},
    ]

    result = _build_layer5_intervention_signals(
        risk_level="warning",
        layer4_scenarios=scenarios,
        in_flight_effective_qty_total=0,
    )

    assert result == {
        "method": "deterministic_unavoidable_stockout_flags",
        "signal_policy": "critical_risk_thresholds",
        "unavoidable_stockout": False,
        "signals": [],
        "reason": "none",
        "aggressive_stockout_risk_proxy": 0.05,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        },
    }


def test_layer2_allocation_decision_tie_break_is_hold():
    stock_health_metrics = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "current_stock": 10,
            "in_flight": 0,
            "velocity_main": 0.85,
            "velocity_assorti": 1.0,
            "capital_locked": 10.0,
        }
    ]

    decisions, summary = _build_layer2_allocation_decisions(
        stock_health_metrics=stock_health_metrics,
        lead_time_days_total=30,
    )

    assert summary == {"main": 0, "assorti": 0, "hold": 1}
    assert len(decisions) == 1
    assert decisions[0]["profit_if_main_until_eta"] == 0.85
    assert decisions[0]["profit_if_assorti_until_eta"] == 0.85
    assert decisions[0]["profit_gap_until_eta"] == 0.0
    assert decisions[0]["decision_reason"] == "profit_tie_hold"
    assert decisions[0]["tie_break_applied"] is True
    assert decisions[0]["near_tie"] is True
    assert decisions[0]["allocation_decision"] == "hold"


@pytest.mark.parametrize(
    (
        "case_name",
        "stock_metric",
        "base_line_qty",
        "available_bundles_for_cover",
        "total_daily_sales",
        "reorder_point_days",
        "risk_level",
        "in_flight_effective_qty_total",
        "expected",
    ),
    [
        pytest.param(
            "stockout_risk_case",
            {
                "color_id": 10,
                "size_id": 1,
                "eta_days": 10,
                "current_stock": 20,
                "in_flight": 0,
                "velocity_main": 3.0,
                "velocity_assorti": 1.5,
                "capital_locked": 100.0,
                "stockout_risk": 0.9,
                "overstock_risk": 0.1,
            },
            120,
            20,
            8.0,
            40,
            "critical",
            0,
            {
                "layer2_decision": "main",
                "layer2_summary": {"main": 1, "assorti": 0, "hold": 0},
                "layer3_qty_after": 150,
                "layer3_qty_delta_vs_base": 30,
                "reorder_qty": 150,
                "layer4_purchase_units": [120, 150, 180],
                "layer4_capital": [120.0, 150.0, 180.0],
                "capital_delta_aggressive_vs_conservative": 60.0,
                "layer5_signals": ["accelerate_production"],
                "layer5_reason": "no_effective_in_flight_and_high_stockout_risk",
                "action": "order_minimum_only",
            },
            id="stockout",
        ),
        pytest.param(
            "balanced_case",
            {
                "color_id": 10,
                "size_id": 1,
                "eta_days": 10,
                "current_stock": 30,
                "in_flight": 10,
                "velocity_main": 1.0,
                "velocity_assorti": 2.0,
                "capital_locked": 80.0,
                "stockout_risk": 0.4,
                "overstock_risk": 0.4,
            },
            100,
            180,
            5.0,
            40,
            "warning",
            20,
            {
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer3_qty_after": 73,
                "layer3_qty_delta_vs_base": -2,
                "reorder_qty": 73,
                "layer4_purchase_units": [59, 73, 88],
                "layer4_capital": [59.0, 73.0, 88.0],
                "capital_delta_aggressive_vs_conservative": 29.0,
                "layer5_signals": [],
                "layer5_reason": "none",
                "action": "order_minimum_only",
            },
            id="balanced",
        ),
        pytest.param(
            "overstock_case",
            {
                "color_id": 10,
                "size_id": 1,
                "eta_days": 10,
                "current_stock": 200,
                "in_flight": 50,
                "velocity_main": 1.7,
                "velocity_assorti": 2.0,
                "capital_locked": 120.0,
                "stockout_risk": 0.05,
                "overstock_risk": 0.95,
            },
            40,
            1000,
            4.0,
            40,
            "overstock",
            40,
            {
                "layer2_decision": "hold",
                "layer2_summary": {"main": 0, "assorti": 0, "hold": 1},
                "layer3_qty_after": 4,
                "layer3_qty_delta_vs_base": -10,
                "reorder_qty": 4,
                "layer4_purchase_units": [4, 4, 5],
                "layer4_capital": [4.0, 4.0, 5.0],
                "capital_delta_aggressive_vs_conservative": 1.0,
                "layer5_signals": [],
                "layer5_reason": "none",
                "action": "wait",
            },
            id="overstock",
        ),
    ],
)
def test_decision_quality_case_studies_are_deterministic(
    case_name,
    stock_metric,
    base_line_qty,
    available_bundles_for_cover,
    total_daily_sales,
    reorder_point_days,
    risk_level,
    in_flight_effective_qty_total,
    expected,
):
    stock_health_metrics = [stock_metric]

    layer2_decisions, layer2_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=stock_health_metrics,
        lead_time_days_total=30,
    )

    assert len(layer2_decisions) == 1
    layer2 = layer2_decisions[0]
    assert layer2_summary == expected["layer2_summary"]
    assert layer2["allocation_decision"] == expected["layer2_decision"]

    if expected["layer2_decision"] == "main":
        assert layer2["profit_if_main_until_eta"] > layer2["profit_if_assorti_until_eta"]
    elif expected["layer2_decision"] == "assorti":
        assert layer2["profit_if_assorti_until_eta"] > layer2["profit_if_main_until_eta"]
    else:
        assert layer2["profit_if_main_until_eta"] == layer2["profit_if_assorti_until_eta"]

    line_key = (int(stock_metric["color_id"]), int(stock_metric["size_id"]))
    line_qty = {line_key: base_line_qty}
    layer3_decision_by_line, layer3_purchase_shaping = _apply_layer3_purchase_shaping(
        line_qty=line_qty,
        layer2_allocation_decisions=layer2_decisions,
        layer1_stock_health_metrics=stock_health_metrics,
    )

    assert layer3_decision_by_line[line_key] == expected["layer2_decision"]
    assert layer3_purchase_shaping["qty_before"] == base_line_qty
    assert line_qty[line_key] == expected["layer3_qty_after"]
    assert layer3_purchase_shaping["qty_after"] == expected["layer3_qty_after"]
    assert (
        layer3_purchase_shaping["qty_delta_vs_base"]
        == expected["layer3_qty_delta_vs_base"]
    )

    candidate_total_units = sum(line_qty.values())
    assert candidate_total_units == expected["reorder_qty"]

    layer4_scenarios = _build_layer4_scenarios(
        base_purchase_units=candidate_total_units,
        available_bundles_for_cover=available_bundles_for_cover,
        total_daily_sales=total_daily_sales,
        reorder_point_days=reorder_point_days,
        expected_horizon_sales=total_daily_sales * 90,
        layer3_purchase_shaping=layer3_purchase_shaping,
    )

    assert [item["scenario"] for item in layer4_scenarios] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert [item["purchase_units"] for item in layer4_scenarios] == expected[
        "layer4_purchase_units"
    ]
    assert [item["total_capital_required"] for item in layer4_scenarios] == expected[
        "layer4_capital"
    ]
    assert (
        float(layer4_scenarios[2]["total_capital_required"])
        - float(layer4_scenarios[0]["total_capital_required"])
    ) == expected["capital_delta_aggressive_vs_conservative"]

    layer4_stockout_risks = [float(item["stockout_risk_proxy"]) for item in layer4_scenarios]
    assert layer4_stockout_risks[0] >= layer4_stockout_risks[1] >= layer4_stockout_risks[2]

    layer5_intervention = _build_layer5_intervention_signals(
        risk_level=risk_level,
        layer4_scenarios=layer4_scenarios,
        in_flight_effective_qty_total=in_flight_effective_qty_total,
    )
    assert layer5_intervention["signals"] == expected["layer5_signals"]
    assert layer5_intervention["reason"] == expected["layer5_reason"]

    action = _choose_action(
        risk_level=risk_level,
        candidate_units=candidate_total_units,
        allow_order_with_buffer=False,
    )
    assert action == expected["action"]

    # Layer 5 is signal-only and must not directly force recommendation action type.
    if case_name == "stockout_risk_case":
        assert layer5_intervention["signals"] == ["accelerate_production"]
        assert action == "order_minimum_only"


@pytest.mark.parametrize(
    (
        "case_name",
        "layer1_input",
        "base_line_qty",
        "available_bundles_for_cover",
        "total_daily_sales",
        "reorder_point_days",
        "risk_level",
        "in_flight_effective_qty_total",
        "expected",
    ),
    [
        pytest.param(
            "stockout",
            {
                "daily_sales_main": 3.0,
                "daily_sales_assorti": 1.5,
                "current_stock": 20,
                "in_flight": 0,
                "eta_days": 10,
                "target_coverage_days": 60,
            },
            120,
            20,
            8.0,
            40,
            "critical",
            0,
            {
                "layer1": {
                    "velocity_main": 3.0,
                    "velocity_assorti": 1.5,
                    "coverage_days": 4.44,
                    "stockout_risk": 0.8889,
                    "overstock_risk": 0.0,
                    "capital_locked": 20.0,
                },
                "layer2_decision": "main",
                "layer2_summary": {"main": 1, "assorti": 0, "hold": 0},
                "layer2_near_tie_count": 0,
                "layer2_tie_count": 0,
                "layer3_qty_after": 150,
                "layer3_qty_delta_vs_base": 30,
                "reorder_qty": 150,
                "layer4_purchase_units": [120, 150, 180],
                "layer4_capital": [120.0, 150.0, 180.0],
                "capital_delta_aggressive_vs_conservative": 60.0,
                "layer5_signals": ["accelerate_production"],
                "layer5_reason": "no_effective_in_flight_and_high_stockout_risk",
                "action": "order_minimum_only",
            },
            id="stockout",
        ),
        pytest.param(
            "balanced",
            {
                "daily_sales_main": 1.0,
                "daily_sales_assorti": 2.0,
                "current_stock": 90,
                "in_flight": 0,
                "eta_days": 10,
                "target_coverage_days": 60,
            },
            100,
            180,
            5.0,
            40,
            "warning",
            20,
            {
                "layer1": {
                    "velocity_main": 1.0,
                    "velocity_assorti": 2.0,
                    "coverage_days": 30.0,
                    "stockout_risk": 0.25,
                    "overstock_risk": 0.0,
                    "capital_locked": 90.0,
                },
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer2_near_tie_count": 0,
                "layer2_tie_count": 0,
                "layer3_qty_after": 80,
                "layer3_qty_delta_vs_base": 5,
                "reorder_qty": 80,
                "layer4_purchase_units": [64, 80, 96],
                "layer4_capital": [64.0, 80.0, 96.0],
                "capital_delta_aggressive_vs_conservative": 32.0,
                "layer5_signals": [],
                "layer5_reason": "none",
                "action": "order_minimum_only",
            },
            id="balanced",
        ),
        pytest.param(
            "overstock",
            {
                "daily_sales_main": 1.7,
                "daily_sales_assorti": 2.0,
                "current_stock": 300,
                "in_flight": 50,
                "eta_days": 10,
                "target_coverage_days": 20,
            },
            40,
            1000,
            4.0,
            40,
            "overstock",
            40,
            {
                "layer1": {
                    "velocity_main": 1.7,
                    "velocity_assorti": 2.0,
                    "coverage_days": 94.59,
                    "stockout_risk": 0.0,
                    "overstock_risk": 1.0,
                    "capital_locked": 350.0,
                },
                "layer2_decision": "hold",
                "layer2_summary": {"main": 0, "assorti": 0, "hold": 1},
                "layer2_near_tie_count": 1,
                "layer2_tie_count": 1,
                "layer3_qty_after": 4,
                "layer3_qty_delta_vs_base": -10,
                "reorder_qty": 4,
                "layer4_purchase_units": [4, 4, 5],
                "layer4_capital": [4.0, 4.0, 5.0],
                "capital_delta_aggressive_vs_conservative": 1.0,
                "layer5_signals": [],
                "layer5_reason": "none",
                "action": "wait",
            },
            id="overstock",
        ),
    ],
)
def test_decision_quality_case_studies_are_deterministic_across_layer1_to_layer5(
    case_name,
    layer1_input,
    base_line_qty,
    available_bundles_for_cover,
    total_daily_sales,
    reorder_point_days,
    risk_level,
    in_flight_effective_qty_total,
    expected,
):
    stock_health_metrics = _build_layer1_stock_health_metrics(
        bundle_type_ids=[101, 202],
        demand_by_bundle={
            101: layer1_input["daily_sales_main"],
            202: layer1_input["daily_sales_assorti"],
        },
        recipe_colors_by_bundle={
            101: {10},
            202: {10},
        },
        color_to_sizes={10: [1]},
        size_weights={1: 1.0},
        current_stock_by_color_size={(10, 1): layer1_input["current_stock"]},
        in_flight_effective_by_color_size={(10, 1): layer1_input["in_flight"]},
        in_flight_eta_days_by_color_size={(10, 1): layer1_input["eta_days"]},
        assorti_by_bundle_type={
            101: False,
            202: True,
        },
        reorder_point_days=reorder_point_days,
        target_coverage_days=layer1_input["target_coverage_days"],
    )

    assert len(stock_health_metrics) == 1
    layer1_metric = stock_health_metrics[0]
    assert layer1_metric["velocity_main"] == expected["layer1"]["velocity_main"]
    assert layer1_metric["velocity_assorti"] == expected["layer1"]["velocity_assorti"]
    assert layer1_metric["coverage_days"] == expected["layer1"]["coverage_days"]
    assert layer1_metric["stockout_risk"] == expected["layer1"]["stockout_risk"]
    assert layer1_metric["overstock_risk"] == expected["layer1"]["overstock_risk"]
    assert layer1_metric["capital_locked"] == expected["layer1"]["capital_locked"]

    layer1_contract = _build_layer1_contract_summary(stock_health_metrics)
    assert layer1_contract["status"] == "ok"

    layer2_decisions, layer2_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=stock_health_metrics,
        lead_time_days_total=30,
    )
    assert len(layer2_decisions) == 1
    assert layer2_summary == expected["layer2_summary"]
    assert layer2_decisions[0]["allocation_decision"] == expected["layer2_decision"]

    layer2_decision_quality = _build_layer2_decision_quality_summary(layer2_decisions)
    assert layer2_decision_quality["decision_count"] == 1
    assert layer2_decision_quality["near_tie_count"] == expected["layer2_near_tie_count"]
    assert layer2_decision_quality["tie_count"] == expected["layer2_tie_count"]

    layer2_contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=layer2_decisions,
        layer2_allocation_summary=layer2_summary,
    )
    assert layer2_contract["status"] == "ok"
    assert layer2_contract["checks"]["decision_reason_matches_allocation"] is True
    assert layer2_contract["checks"]["allocation_matches_profit_gate"] is True
    assert layer2_contract["checks"]["tie_break_applied_matches_profit_tie"] is True
    assert layer2_contract["checks"]["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_contract["checks"]["profit_gap_consistent_with_profits"] is True
    assert layer2_contract["checks"]["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_contract["checks"]["capital_locked_metric_valid"] is True

    line_qty = {(10, 1): base_line_qty}
    _, layer3_purchase_shaping = _apply_layer3_purchase_shaping(
        line_qty=line_qty,
        layer2_allocation_decisions=layer2_decisions,
        layer1_stock_health_metrics=stock_health_metrics,
    )
    assert line_qty[(10, 1)] == expected["layer3_qty_after"]
    assert layer3_purchase_shaping["qty_after"] == expected["layer3_qty_after"]
    assert layer3_purchase_shaping["qty_delta_vs_base"] == expected["layer3_qty_delta_vs_base"]

    candidate_total_units = sum(line_qty.values())
    assert candidate_total_units == expected["reorder_qty"]

    layer4_scenarios = _build_layer4_scenarios(
        base_purchase_units=candidate_total_units,
        available_bundles_for_cover=available_bundles_for_cover,
        total_daily_sales=total_daily_sales,
        reorder_point_days=reorder_point_days,
        expected_horizon_sales=total_daily_sales * 90,
        layer3_purchase_shaping=layer3_purchase_shaping,
    )
    assert [item["purchase_units"] for item in layer4_scenarios] == expected["layer4_purchase_units"]
    assert [item["total_capital_required"] for item in layer4_scenarios] == expected["layer4_capital"]
    assert (
        float(layer4_scenarios[2]["total_capital_required"])
        - float(layer4_scenarios[0]["total_capital_required"])
    ) == expected["capital_delta_aggressive_vs_conservative"]

    layer5_intervention = _build_layer5_intervention_signals(
        risk_level=risk_level,
        layer4_scenarios=layer4_scenarios,
        in_flight_effective_qty_total=in_flight_effective_qty_total,
    )
    assert layer5_intervention["signals"] == expected["layer5_signals"]
    assert layer5_intervention["reason"] == expected["layer5_reason"]

    action = _choose_action(
        risk_level=risk_level,
        candidate_units=candidate_total_units,
        allow_order_with_buffer=False,
    )
    assert action == expected["action"]

    if case_name == "stockout":
        # Explicit guardrail: intervention signal does not override recommendation action policy.
        assert layer5_intervention["signals"] == ["accelerate_production"]
        assert action == "order_minimum_only"


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
    layer2_step = next(
        (step for step in body["explanation"]["steps"] if "Layer 2 allocation" in step),
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
    assert "decision_gate=profit_until_eta" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step

    layer2_contract_checks = body["explanation"]["meta"]["layer_2_allocation"]["contract"]["checks"]
    assert layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_contract_checks["capital_locked_metric_valid"] is True

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


def test_production_order_proposal_from_wb_compact_explainability_mode(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-COMPACT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-COMPACT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-COMPACT",
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
        "explainability_mode": EXPLAINABILITY_MODE_COMPACT,
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
    steps = body["explanation"]["steps"]
    assert any("WB ingestion adapter" in step for step in steps)
    assert any("Layer 2 allocation" in step for step in steps)
    assert any("Explainability compact mode: omitted_steps=" in step for step in steps)
    layer2_step = next((step for step in steps if "Layer 2 allocation" in step), "")
    assert "decision_gate=profit_until_eta" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step

    meta = body["explanation"]["meta"]
    assert meta["explainability"]["mode"] == EXPLAINABILITY_MODE_COMPACT
    assert meta["layer_1_stock_health"]["contract"]["status"] == "ok"
    assert "decisions" not in meta["layer_2_allocation"]
    assert meta["layer_2_allocation"]["contract"]["status"] == "ok"
    layer2_compact_contract_checks = meta["layer_2_allocation"]["contract"]["checks"]
    assert layer2_compact_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_compact_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_compact_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_compact_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_compact_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_compact_contract_checks["capital_locked_metric_valid"] is True
    assert meta["layer_2_allocation"]["decision_quality"]["profit_gate_primary"] is True
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert meta["layer_3_purchase_shaping"]["contract"]["status"] == "ok"
    assert meta["layer_4_scenarios"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_policy"] == "critical_risk_thresholds"
    assert meta["layer_5_intervention"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["layer_3_calibration"]["method"] == "risk_weighted_factor_clamp"
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    }
    from_wb_meta = meta["from_wb"]
    assert "daily_sales_by_bundle" not in from_wb_meta
    assert "wb_stock_by_bundle" not in from_wb_meta
    assert "wb_stock_updated_at_by_bundle" not in from_wb_meta
    assert from_wb_meta["freshness"]["status"] in {"fresh", "stale"}
    assert "stock_age_days_by_bundle" not in from_wb_meta["freshness"]
    assert from_wb_meta["snapshot"] == {
        "daily_sales_bundle_count": 1,
        "daily_sales_total": 2.0,
        "wb_stock_bundle_count": 1,
        "wb_stock_total": 20,
        "wb_stock_updated_bundle_count": 1,
    }


def test_production_order_proposal_from_wb_compact_mode_preserves_deterministic_output(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-COMPACT-PARITY",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-COMPACT-PARITY",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-COMPACT-PARITY",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    base_payload = {
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

    full_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=base_payload,
    )
    assert full_response.status_code == 200, full_response.text

    compact_payload = deepcopy(base_payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    full_body = full_response.json()
    compact_body = compact_response.json()
    assert _business_projection(full_body) == _business_projection(compact_body)

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert "decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True


@pytest.mark.parametrize(
    ("profile_name", "sales_qty", "stock_qty"),
    [
        pytest.param("stockout", 600, 10, id="stockout"),
        pytest.param("balanced", 240, 120, id="balanced"),
        pytest.param("overstock", 60, 1500, id="overstock"),
    ],
)
def test_production_order_proposal_from_wb_compact_mode_preserves_deterministic_output_across_profiles(
    client,
    db_session,
    profile_name,
    sales_qty,
    stock_qty,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)
    wb_sku = f"WB-PO-BT1-COMPACT-PROFILE-{profile_name.upper()}"

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku=wb_sku,
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku=wb_sku,
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=sales_qty,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku=wb_sku,
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=stock_qty,
            updated_at=stock_updated_at,
        )
    )
    db_session.commit()

    base_payload = {
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

    full_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=base_payload,
    )
    assert full_response.status_code == 200, full_response.text

    compact_payload = deepcopy(base_payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    full_body = full_response.json()
    compact_body = compact_response.json()
    assert _business_projection(full_body) == _business_projection(compact_body)

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert "decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    if profile_name == "overstock":
        assert compact_body["risk_level"] == "overstock"


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
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "freshness_mode"]
    assert detail[0]["type"] == "literal_error"


def test_production_order_proposal_from_wb_validation_error_duplicate_bundle_type_ids(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": 1,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [1, 1],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 422, response.text
    assert "bundle_type_ids contains duplicates" in response.text


def test_production_order_proposal_validation_error_invalid_layer5_threshold_order(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json={
            "article_id": 1,
            "planning_horizon_days": 90,
            "bundle_daily_sales": [
                {
                    "bundle_type_id": 1,
                    "daily_sales": 1.0,
                }
            ],
            "bundle_stock": [
                {
                    "bundle_type_id": 1,
                    "wb_qty": 0,
                    "local_qty": 0,
                }
            ],
            "in_flight_supply": [],
            "size_weights": {},
            "overrides": {
                "layer5_unavoidable_stockout_risk_threshold": 0.6,
                "layer5_accelerate_production_risk_threshold": 0.2,
            },
        },
    )
    assert response.status_code == 422, response.text
    assert (
        "layer5_accelerate_production_risk_threshold must be greater than or equal to "
        "layer5_unavoidable_stockout_risk_threshold"
    ) in response.text


def test_production_order_proposal_validation_error_duplicate_bundle_stock_bundle_type_id(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json={
            "article_id": 1,
            "planning_horizon_days": 90,
            "bundle_daily_sales": [
                {
                    "bundle_type_id": 1,
                    "daily_sales": 1.0,
                }
            ],
            "bundle_stock": [
                {
                    "bundle_type_id": 1,
                    "wb_qty": 0,
                    "local_qty": 0,
                },
                {
                    "bundle_type_id": 1,
                    "wb_qty": 1,
                    "local_qty": 0,
                },
            ],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 422, response.text
    assert "bundle_stock contains duplicate bundle_type_id" in response.text


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
    detail = response.json()["detail"]
    detail_locs = {tuple(item["loc"]) for item in detail}
    assert ("body", "planning_horizon_days") in detail_locs
    assert ("body", "bundle_daily_sales") in detail_locs
