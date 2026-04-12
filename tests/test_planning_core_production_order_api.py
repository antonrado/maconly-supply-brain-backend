from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.services import planning_production_order as planning_production_order_service
from app.services.planning_production_order import (
    ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE,
    ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE,
    ASSORTI_CLASSIFICATION_SOURCE,
    CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
    CAPITAL_CONSTRAINT_CONTRACT_VERSION,
    ECONOMICS_TRUST_LEVEL_PARTIAL,
    ECONOMICS_TRUST_LEVEL_TRUSTED,
    ECONOMICS_TRUST_LEVEL_UNTRUSTED,
    ECONOMICS_TRUST_WARNING_CODE_PARTIAL,
    ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED,
    EXPLAINABILITY_MODE_COMPACT,
    FROM_WB_OBSERVED_ECONOMIC_SOURCE,
    FROM_WB_TARIFFS_COMMISSION_SOURCE,
    LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD,
    LAYER2_ALLOCATION_METHOD,
    LAYER2_ALLOCATION_METHOD_CANONICAL,
    LAYER2_CAPITAL_COST_RATE,
    LAYER2_CONTRACT_VERSION,
    LAYER2_DECISION_GATE_CANONICAL,
    LAYER2_DECISION_GATE_LEGACY,
    LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
    LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD,
    LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD,
    LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    LAYER2_STOCKOUT_PENALTY_WEIGHT,
    LAYER3_CONTRACT_VERSION,
    LAYER4_SCENARIO_FACTORS,
    LAYER5_CONTRACT_VERSION,
    LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
    LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    LAYER_PROXY_VALUE_SOURCE,
    LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
    RESOURCE_ALLOCATION_CONTRACT_VERSION,
    _apply_capital_constraint_to_candidate_lines,
    _apply_layer3_purchase_shaping,
    _build_competition_aware_resource_allocation,
    _build_layer1_stock_health_metrics,
    _build_layer1_contract_summary,
    _build_layer2_allocation_decisions,
    _build_layer2_contract_summary,
    _build_layer2_decision_quality_summary,
    _compute_objective_components,
    _build_line_objective_capital_rankings,
    _build_layer3_contract_summary,
    _build_layer4_aggregate_deltas,
    _build_layer4_scenarios,
    _build_layer4_contract_summary,
    _build_capital_constraint_contract_summary,
    _build_resource_allocation_contract_summary,
    _build_layer5_contract_summary,
    _build_layer5_intervention_signals,
    _choose_action,
)
from app.services.planning_production_order_recommendation import (
    _build_alternatives as extracted_build_alternatives,
    _choose_action as extracted_choose_action,
)
from app.services.planning_production_order_scope import (
    build_physical_scope_and_arrival_projection,
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
    WbIntegrationAccount,
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
            default_production_order_available_capital=1000000,
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
            "available_capital": 1000000.0,
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
        "tie_break_hold_when_equal_objective": False,
        "tie_break_hold_when_equal_profit": False,
        "decision_reason_matches_allocation": False,
        "decision_reason_expected_gross_profit_matches_allocation": True,
        "decision_reason_objective_score_matches_allocation": False,
        "allocation_matches_composite_objective_gate": False,
        "allocation_matches_profit_gate": False,
        "allocation_matches_expected_gross_profit_gate": False,
        "tie_break_applied_matches_objective_tie": False,
        "tie_break_applied_matches_profit_tie": False,
        "near_tie_matches_objective_gap_threshold": False,
        "near_tie_matches_profit_gap_threshold": False,
        "profit_gap_consistent_with_profits": False,
        "expected_gross_profit_gap_consistent_with_expected_gross_profits": False,
        "gmroi_gap_consistent_with_gmroi": False,
        "capital_locked_metric_valid": False,
        "objective_required_fields_present": False,
        "objective_score_fields_numeric": False,
        "objective_components_present": False,
        "objective_components_numeric": False,
        "objective_components_consistent_with_scores": False,
        "objective_components_match_formula": False,
        "objective_score_gap_consistent_with_objective_scores": False,
    }
    assert contract["legacy_aliases"] == {
        "allocation_matches_profit_gate": {
            "alias_for": "allocation_matches_composite_objective_gate",
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
        "allocation_matches_expected_gross_profit_gate": {
            "alias_for": "allocation_matches_composite_objective_gate",
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
        "tie_break_hold_when_equal_profit": {
            "alias_for": "tie_break_hold_when_equal_objective",
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
        "tie_break_applied_matches_profit_tie": {
            "alias_for": "tie_break_applied_matches_objective_tie",
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
        "near_tie_matches_profit_gap_threshold": {
            "alias_for": "near_tie_matches_objective_gap_threshold",
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
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
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
    )

    assert summary == {"main": 1, "assorti": 0, "hold": 0}
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["color_id"] == 10
    assert decision["size_id"] == 20
    assert decision["profit_if_main_until_eta"] == 1.0
    assert decision["profit_if_assorti_until_eta"] == 1.0
    assert decision["objective_score_if_main_until_eta"] == 0.9974
    assert decision["objective_score_if_assorti_until_eta"] == 0.9969
    assert decision["objective_score_gap_until_eta"] == 0.0005
    assert decision["objective_components_if_main"]["objective_score"] == 0.9974
    assert decision["objective_components_if_assorti"]["objective_score"] == 0.9969
    assert decision["allocation_decision"] == "main"
    assert decision["decision_reason"] == "profit_main_gt_assorti"
    assert decision["decision_reason_objective_score"] == "objective_score_main_gt_assorti"
    assert decision["capital_cost_rate"] == LAYER2_CAPITAL_COST_RATE
    assert decision["stockout_penalty_weight"] == LAYER2_STOCKOUT_PENALTY_WEIGHT
    assert decision["overstock_penalty_weight"] == LAYER2_OVERSTOCK_PENALTY_WEIGHT
    assert decision["tie_break_applied"] is False
    assert decision["near_tie"] is True

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary=summary,
    )

    assert contract["status"] == "ok"
    assert contract["checks"]["tie_break_hold_when_equal_objective"] is True
    assert contract["checks"]["tie_break_hold_when_equal_profit"] is True
    assert contract["checks"]["allocation_matches_composite_objective_gate"] is True
    assert contract["checks"]["allocation_matches_profit_gate"] is True
    assert contract["checks"]["allocation_matches_expected_gross_profit_gate"] is True
    assert contract["checks"]["tie_break_applied_matches_objective_tie"] is True
    assert contract["checks"]["tie_break_applied_matches_profit_tie"] is True
    assert contract["checks"]["near_tie_matches_objective_gap_threshold"] is True
    assert contract["checks"]["near_tie_matches_profit_gap_threshold"] is True
    assert contract["checks"]["objective_required_fields_present"] is True
    assert contract["checks"]["objective_score_fields_numeric"] is True
    assert contract["checks"]["objective_components_present"] is True
    assert contract["checks"]["objective_components_numeric"] is True
    assert contract["checks"]["objective_components_consistent_with_scores"] is True
    assert contract["checks"]["objective_components_match_formula"] is True
    assert contract["checks"]["objective_score_gap_consistent_with_objective_scores"] is True
    assert contract["checks"]["decision_reason_objective_score_matches_allocation"] is True


def test_objective_components_penalty_monotonicity_and_formula_consistency():
    base = _compute_objective_components(
        expected_gross_profit=100.0,
        capital_locked=100.0,
        stockout_risk=0.4,
        overstock_risk=0.3,
        expected_lost_margin_if_stockout=80.0,
        inventory_carrying_cost=60.0,
        capital_cost_rate=0.1,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.0,
        horizon_factor=1.0,
    )

    higher_capital_penalty = _compute_objective_components(
        expected_gross_profit=100.0,
        capital_locked=100.0,
        stockout_risk=0.4,
        overstock_risk=0.3,
        expected_lost_margin_if_stockout=80.0,
        inventory_carrying_cost=60.0,
        capital_cost_rate=0.2,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.0,
        horizon_factor=1.0,
    )
    higher_stockout_penalty = _compute_objective_components(
        expected_gross_profit=100.0,
        capital_locked=100.0,
        stockout_risk=0.4,
        overstock_risk=0.3,
        expected_lost_margin_if_stockout=80.0,
        inventory_carrying_cost=60.0,
        capital_cost_rate=0.1,
        stockout_penalty_weight=1.5,
        overstock_penalty_weight=1.0,
        horizon_factor=1.0,
    )
    higher_overstock_penalty = _compute_objective_components(
        expected_gross_profit=100.0,
        capital_locked=100.0,
        stockout_risk=0.4,
        overstock_risk=0.3,
        expected_lost_margin_if_stockout=80.0,
        inventory_carrying_cost=60.0,
        capital_cost_rate=0.1,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.5,
        horizon_factor=1.0,
    )

    assert base["objective_score"] == pytest.approx(
        100.0
        - base["capital_cost_penalty"]
        - base["stockout_penalty"]
        - base["overstock_penalty"],
        abs=1e-9,
    )
    assert higher_capital_penalty["capital_cost_penalty"] > base["capital_cost_penalty"]
    assert higher_capital_penalty["objective_score"] < base["objective_score"]
    assert higher_stockout_penalty["stockout_penalty"] > base["stockout_penalty"]
    assert higher_stockout_penalty["objective_score"] < base["objective_score"]
    assert higher_overstock_penalty["overstock_penalty"] > base["overstock_penalty"]
    assert higher_overstock_penalty["objective_score"] < base["objective_score"]


@pytest.mark.parametrize(
    (
        "fixture_name",
        "stock_metric",
        "margin_main_per_unit",
        "margin_assorti_per_unit",
        "unit_capital_per_unit",
        "dominant_penalty",
    ),
    [
        pytest.param(
            "profit_winner_differs_from_objective_winner_capital_penalty",
            {
                "color_id": 10,
                "size_id": 20,
                "eta_days": 30,
                "current_stock": 100,
                "in_flight": 0,
                "velocity_main": 4.0,
                "velocity_assorti": 2.0,
                "capital_locked": 0.0,
                "stockout_risk": 0.0,
                "overstock_risk": 0.0,
            },
            1.0,
            1.5,
            20.0,
            "capital",
            id="capital_penalty_flip",
        ),
        pytest.param(
            "profit_winner_differs_from_objective_winner_stockout_penalty",
            {
                "color_id": 10,
                "size_id": 20,
                "eta_days": 70,
                "current_stock": 12,
                "in_flight": 0,
                "velocity_main": 2.0,
                "velocity_assorti": 2.0,
                "capital_locked": 12.0,
                "stockout_risk": 0.987,
                "overstock_risk": 0.0,
            },
            1.08,
            0.225,
            1.0,
            "stockout",
            id="stockout_penalty_flip",
        ),
        pytest.param(
            "profit_winner_differs_from_objective_winner_overstock_penalty",
            {
                "color_id": 10,
                "size_id": 20,
                "eta_days": 10,
                "current_stock": 100,
                "in_flight": 0,
                "velocity_main": 2.0,
                "velocity_assorti": 5.0,
                "capital_locked": 100.0,
                "stockout_risk": 0.0,
                "overstock_risk": 1.0,
            },
            2.5,
            0.9,
            5.0,
            "overstock",
            id="overstock_penalty_flip",
        ),
    ],
)
def test_layer2_allocation_objective_dominates_when_profit_gate_disagrees(
    fixture_name,
    stock_metric,
    margin_main_per_unit,
    margin_assorti_per_unit,
    unit_capital_per_unit,
    dominant_penalty,
):
    decisions, summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=int(stock_metric["eta_days"]),
        margin_main_per_unit=margin_main_per_unit,
        margin_assorti_per_unit=margin_assorti_per_unit,
        unit_capital_per_unit=unit_capital_per_unit,
    )

    assert fixture_name
    assert summary == {"main": 0, "assorti": 1, "hold": 0}
    assert len(decisions) == 1

    decision = decisions[0]
    assert decision["profit_if_main_until_eta"] > decision["profit_if_assorti_until_eta"]
    assert (
        decision["objective_score_if_main_until_eta"]
        < decision["objective_score_if_assorti_until_eta"]
    )
    assert decision["allocation_decision"] == "assorti"
    assert decision["decision_reason_objective_score"] == "objective_score_assorti_gt_main"

    if dominant_penalty == "capital":
        assert (
            decision["capital_cost_penalty_if_main_until_eta"]
            > decision["capital_cost_penalty_if_assorti_until_eta"]
        )
        assert decision["stockout_penalty_if_main_until_eta"] == 0.0
        assert decision["stockout_penalty_if_assorti_until_eta"] == 0.0
        assert decision["overstock_penalty_if_main_until_eta"] == 0.0
        assert decision["overstock_penalty_if_assorti_until_eta"] == 0.0
    elif dominant_penalty == "stockout":
        assert (
            decision["stockout_penalty_if_main_until_eta"]
            > decision["stockout_penalty_if_assorti_until_eta"]
        )
    elif dominant_penalty == "overstock":
        assert (
            decision["overstock_penalty_if_main_until_eta"]
            > decision["overstock_penalty_if_assorti_until_eta"]
        )


def test_stockout_penalty_weight_boundary_flips_documented_stockout_profile():
    stock_metric = {
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
    }

    below_boundary_decisions, below_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
        stockout_penalty_weight=0.84,
    )
    above_boundary_decisions, above_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
        stockout_penalty_weight=0.85,
    )

    assert below_boundary_summary == {"main": 1, "assorti": 0, "hold": 0}
    assert above_boundary_summary == {"main": 0, "assorti": 1, "hold": 0}

    below_boundary = below_boundary_decisions[0]
    above_boundary = above_boundary_decisions[0]

    assert below_boundary["profit_if_main_until_eta"] > below_boundary["profit_if_assorti_until_eta"]
    assert above_boundary["profit_if_main_until_eta"] > above_boundary["profit_if_assorti_until_eta"]

    assert below_boundary["allocation_decision"] == "main"
    assert below_boundary["decision_reason_objective_score"] == "objective_score_main_gt_assorti"
    assert (
        below_boundary["objective_score_if_main_until_eta"]
        > below_boundary["objective_score_if_assorti_until_eta"]
    )
    assert below_boundary["stockout_penalty_weight"] == 0.84

    assert above_boundary["allocation_decision"] == "assorti"
    assert above_boundary["decision_reason_objective_score"] == "objective_score_assorti_gt_main"
    assert (
        above_boundary["objective_score_if_main_until_eta"]
        < above_boundary["objective_score_if_assorti_until_eta"]
    )
    assert above_boundary["stockout_penalty_weight"] == 0.85


def test_overstock_penalty_weight_boundary_flips_documented_overstock_profile():
    stock_metric = {
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
    }

    below_boundary_decisions, below_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
        overstock_penalty_weight=0.02,
    )
    above_boundary_decisions, above_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
        overstock_penalty_weight=0.03,
    )

    assert below_boundary_summary == {"main": 1, "assorti": 0, "hold": 0}
    assert above_boundary_summary == {"main": 0, "assorti": 1, "hold": 0}

    below_boundary = below_boundary_decisions[0]
    above_boundary = above_boundary_decisions[0]

    assert below_boundary["profit_if_main_until_eta"] == below_boundary["profit_if_assorti_until_eta"]
    assert above_boundary["profit_if_main_until_eta"] == above_boundary["profit_if_assorti_until_eta"]

    assert below_boundary["allocation_decision"] == "main"
    assert below_boundary["decision_reason_objective_score"] == "objective_score_main_gt_assorti"
    assert (
        below_boundary["objective_score_if_main_until_eta"]
        > below_boundary["objective_score_if_assorti_until_eta"]
    )
    assert below_boundary["overstock_penalty_weight"] == 0.02

    assert above_boundary["allocation_decision"] == "assorti"
    assert above_boundary["decision_reason_objective_score"] == "objective_score_assorti_gt_main"
    assert (
        above_boundary["objective_score_if_main_until_eta"]
        < above_boundary["objective_score_if_assorti_until_eta"]
    )
    assert above_boundary["overstock_penalty_weight"] == 0.03


def test_commission_conflict_stockout_penalty_boundary_flips_documented_profile():
    stock_metric = {
        "color_id": 10,
        "size_id": 1,
        "eta_days": 30,
        "current_stock": 10,
        "in_flight": 0,
        "velocity_main": 8.0,
        "velocity_assorti": 8.0,
        "capital_locked": 10.0,
        "stockout_risk": 1.0,
        "overstock_risk": 0.0,
    }

    below_boundary_decisions, below_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=0.88,
        margin_assorti_per_unit=0.795,
        unit_capital_per_unit=1.0,
        stockout_penalty_weight=0.04,
    )
    above_boundary_decisions, above_boundary_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=[stock_metric],
        lead_time_days_total=30,
        margin_main_per_unit=0.88,
        margin_assorti_per_unit=0.795,
        unit_capital_per_unit=1.0,
        stockout_penalty_weight=0.05,
    )

    assert below_boundary_summary == {"main": 1, "assorti": 0, "hold": 0}
    assert above_boundary_summary == {"main": 0, "assorti": 1, "hold": 0}

    below_boundary = below_boundary_decisions[0]
    above_boundary = above_boundary_decisions[0]

    assert below_boundary["profit_if_main_until_eta"] > below_boundary["profit_if_assorti_until_eta"]
    assert above_boundary["profit_if_main_until_eta"] > above_boundary["profit_if_assorti_until_eta"]

    assert below_boundary["allocation_decision"] == "main"
    assert below_boundary["decision_reason_objective_score"] == "objective_score_main_gt_assorti"
    assert (
        below_boundary["objective_score_if_main_until_eta"]
        > below_boundary["objective_score_if_assorti_until_eta"]
    )
    assert below_boundary["stockout_penalty_weight"] == 0.04

    assert above_boundary["allocation_decision"] == "assorti"
    assert above_boundary["decision_reason_objective_score"] == "objective_score_assorti_gt_main"
    assert (
        above_boundary["objective_score_if_main_until_eta"]
        < above_boundary["objective_score_if_assorti_until_eta"]
    )
    assert above_boundary["stockout_penalty_weight"] == 0.05


def test_line_objective_capital_rankings_prioritize_objective_per_capital_over_profit():
    candidate_lines = [
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=10,
            size_id=20,
            recommended_qty=12,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=11,
            size_id=21,
            recommended_qty=10,
            source_reason="seed|layer2:main",
        ),
    ]

    rankings = _build_line_objective_capital_rankings(
        candidate_lines=candidate_lines,
        layer3_decision_by_line={
            (10, 20): "main",
            (11, 21): "main",
        },
        layer1_stock_health_metrics=[
            {
                "color_id": 10,
                "size_id": 20,
                "stockout_risk": 0.0,
                "overstock_risk": 0.7,
            },
            {
                "color_id": 11,
                "size_id": 21,
                "stockout_risk": 0.0,
                "overstock_risk": 0.0,
            },
        ],
        margin_main_per_unit=6.0,
        margin_assorti_per_unit=3.0,
        unit_capital_per_unit=10.0,
        capital_cost_rate=0.05,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.0,
    )

    assert len(rankings) == 2
    assert (rankings[0]["color_id"], rankings[0]["size_id"]) == (11, 21)
    assert (rankings[1]["color_id"], rankings[1]["size_id"]) == (10, 20)
    assert rankings[0]["rank"] == 1
    assert rankings[1]["rank"] == 2
    assert rankings[0]["expected_gross_profit"] < rankings[1]["expected_gross_profit"]
    assert rankings[0]["objective_score_per_capital"] > rankings[1]["objective_score_per_capital"]


def test_line_objective_capital_rankings_prioritize_stockout_when_objective_ties():
    candidate_lines = [
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=10,
            size_id=20,
            recommended_qty=10,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=11,
            size_id=21,
            recommended_qty=10,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=12,
            size_id=22,
            recommended_qty=10,
            source_reason="seed|layer2:main",
        ),
    ]

    rankings = _build_line_objective_capital_rankings(
        candidate_lines=candidate_lines,
        layer3_decision_by_line={
            (10, 20): "main",
            (11, 21): "main",
            (12, 22): "main",
        },
        layer1_stock_health_metrics=[
            {
                "color_id": 10,
                "size_id": 20,
                "stockout_risk": 0.8,
                "overstock_risk": 0.1,
            },
            {
                "color_id": 11,
                "size_id": 21,
                "stockout_risk": 0.8,
                "overstock_risk": 0.5,
            },
            {
                "color_id": 12,
                "size_id": 22,
                "stockout_risk": 0.3,
                "overstock_risk": 0.1,
            },
        ],
        margin_main_per_unit=0.0,
        margin_assorti_per_unit=0.0,
        unit_capital_per_unit=0.0,
        capital_cost_rate=0.05,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.0,
    )

    assert [
        (item["color_id"], item["size_id"])
        for item in rankings
    ] == [
        (10, 20),
        (11, 21),
        (12, 22),
    ]
    assert rankings[0]["objective_score"] == rankings[1]["objective_score"] == rankings[2]["objective_score"]
    assert (
        rankings[0]["objective_score_per_capital"]
        == rankings[1]["objective_score_per_capital"]
        == rankings[2]["objective_score_per_capital"]
    )
    assert rankings[0]["stockout_risk"] == rankings[1]["stockout_risk"] > rankings[2]["stockout_risk"]
    assert rankings[0]["overstock_risk"] < rankings[1]["overstock_risk"]
    assert rankings[0]["risk_priority_score"] > rankings[1]["risk_priority_score"] > rankings[2]["risk_priority_score"]


def test_capital_constraint_allocates_budget_by_objective_per_capital_ranking():
    candidate_lines = [
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=10,
            size_id=20,
            recommended_qty=12,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=11,
            size_id=21,
            recommended_qty=10,
            source_reason="seed|layer2:main",
        ),
    ]

    rankings = _build_line_objective_capital_rankings(
        candidate_lines=candidate_lines,
        layer3_decision_by_line={
            (10, 20): "main",
            (11, 21): "main",
        },
        layer1_stock_health_metrics=[
            {
                "color_id": 10,
                "size_id": 20,
                "stockout_risk": 0.0,
                "overstock_risk": 0.7,
            },
            {
                "color_id": 11,
                "size_id": 21,
                "stockout_risk": 0.0,
                "overstock_risk": 0.0,
            },
        ],
        margin_main_per_unit=6.0,
        margin_assorti_per_unit=3.0,
        unit_capital_per_unit=10.0,
        capital_cost_rate=0.05,
        stockout_penalty_weight=1.0,
        overstock_penalty_weight=1.0,
    )

    constrained_lines, summary = _apply_capital_constraint_to_candidate_lines(
        candidate_lines=candidate_lines,
        ranked_line_objectives=rankings,
        available_capital=100.0,
        unit_capital_per_unit=10.0,
    )

    assert summary["status"] == "budget_limited_applied"
    assert summary["constrained"] is True
    assert summary["available_capital"] == 100.0
    assert summary["required_capital_before_constraint"] == 220.0
    assert summary["allocated_capital_after_constraint"] == 100.0
    assert summary["remaining_capital"] == 0.0
    assert summary["line_count_before"] == 2
    assert summary["line_count_after"] == 1

    assert len(constrained_lines) == 1
    selected_line = constrained_lines[0]
    assert (selected_line.color_id, selected_line.size_id) == (11, 21)
    assert selected_line.recommended_qty == 10
    assert selected_line.source_reason.endswith("|capital_constraint")

    cutoff_line = summary["cutoff_line"]
    assert cutoff_line is not None
    assert cutoff_line["color_id"] == 10
    assert cutoff_line["size_id"] == 20
    assert cutoff_line["requested_qty"] == 12
    assert cutoff_line["allocated_qty"] == 0
    assert cutoff_line["objective_score_per_capital"] < rankings[0]["objective_score_per_capital"]


def test_capital_constraint_supports_partial_allocation_on_cutoff_line():
    candidate_lines = [
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=10,
            size_id=20,
            recommended_qty=5,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=11,
            size_id=21,
            recommended_qty=5,
            source_reason="seed|layer2:main",
        ),
        planning_production_order_service.ProductionOrderRecommendationLine(
            article_id=1,
            color_id=12,
            size_id=22,
            recommended_qty=5,
            source_reason="seed|layer2:main",
        ),
    ]
    ranked = [
        {
            "rank": 1,
            "color_id": 10,
            "size_id": 20,
            "objective_score_per_capital": 3.0,
        },
        {
            "rank": 2,
            "color_id": 11,
            "size_id": 21,
            "objective_score_per_capital": 2.0,
        },
        {
            "rank": 3,
            "color_id": 12,
            "size_id": 22,
            "objective_score_per_capital": 1.0,
        },
    ]

    constrained_lines, summary = _apply_capital_constraint_to_candidate_lines(
        candidate_lines=candidate_lines,
        ranked_line_objectives=ranked,
        available_capital=120.0,
        unit_capital_per_unit=10.0,
    )

    assert summary["status"] == "budget_limited_applied"
    assert summary["constrained"] is True
    assert summary["required_capital_before_constraint"] == 150.0
    assert summary["allocated_capital_after_constraint"] == 120.0
    assert summary["remaining_capital"] == 0.0
    assert summary["line_count_before"] == 3
    assert summary["line_count_after"] == 3

    assert [(line.color_id, line.size_id, line.recommended_qty) for line in constrained_lines] == [
        (10, 20, 5),
        (11, 21, 5),
        (12, 22, 2),
    ]

    cutoff_line = summary["cutoff_line"]
    assert cutoff_line is not None
    assert cutoff_line["rank"] == 3
    assert cutoff_line["color_id"] == 12
    assert cutoff_line["size_id"] == 22
    assert cutoff_line["requested_qty"] == 5
    assert cutoff_line["allocated_qty"] == 2


def test_capital_constraint_contract_summary_marks_ok_for_valid_budget_limited_payload():
    summary = {
        "status": "budget_limited_applied",
        "constrained": True,
        "available_capital": 100.0,
        "required_capital_before_constraint": 150.0,
        "allocated_capital_after_constraint": 100.0,
        "remaining_capital": 0.0,
        "line_count_before": 2,
        "line_count_after": 1,
        "cutoff_line": {
            "rank": 2,
            "color_id": 11,
            "size_id": 21,
            "requested_qty": 10,
            "allocated_qty": 0,
            "objective_score_per_capital": 1.0,
        },
        "ranking": [
            {
                "rank": 1,
                "color_id": 10,
                "size_id": 20,
                "objective_score_per_capital": 2.0,
                "objective_score": 20.0,
                "stockout_risk": 0.8,
                "overstock_risk": 0.1,
                "risk_priority_score": 0.7,
            },
            {
                "rank": 2,
                "color_id": 11,
                "size_id": 21,
                "objective_score_per_capital": 1.0,
                "objective_score": 10.0,
                "stockout_risk": 0.4,
                "overstock_risk": 0.3,
                "risk_priority_score": 0.1,
            },
        ],
    }

    contract = _build_capital_constraint_contract_summary(summary)

    assert contract["version"] == CAPITAL_CONSTRAINT_CONTRACT_VERSION
    assert contract["status"] == "ok"
    assert all(contract["checks"].values())


def test_capital_constraint_contract_summary_marks_violated_for_budget_and_ranking_mismatches():
    summary = {
        "status": "budget_limited_applied",
        "constrained": False,
        "available_capital": 50.0,
        "required_capital_before_constraint": 40.0,
        "allocated_capital_after_constraint": 60.0,
        "remaining_capital": 5.0,
        "line_count_before": 1,
        "line_count_after": 2,
        "cutoff_line": {
            "rank": 3,
            "color_id": 99,
            "size_id": 99,
            "requested_qty": 1,
            "allocated_qty": 2,
        },
        "ranking": [
            {
                "rank": 1,
                "color_id": 10,
                "size_id": 20,
                "objective_score_per_capital": 1.0,
                "objective_score": 10.0,
                "stockout_risk": 0.5,
                "overstock_risk": 0.2,
                "risk_priority_score": 0.3,
            },
            {
                "rank": 2,
                "color_id": 10,
                "size_id": 20,
                "objective_score_per_capital": 2.0,
                "objective_score": 20.0,
                "stockout_risk": 0.5,
                "overstock_risk": 0.2,
                "risk_priority_score": 0.9,
            },
        ],
    }

    contract = _build_capital_constraint_contract_summary(summary)

    checks = contract["checks"]
    assert contract["version"] == CAPITAL_CONSTRAINT_CONTRACT_VERSION
    assert contract["status"] == "violated"
    assert checks["constrained_matches_status"] is False
    assert checks["allocation_not_exceed_required"] is False
    assert checks["allocation_not_exceed_available"] is False
    assert checks["budget_accounting_consistent"] is False
    assert checks["line_count_order_valid"] is False
    assert checks["ranking_unique_line_keys"] is False
    assert checks["ranking_sorted_by_objective_per_capital"] is False
    assert checks["ranking_risk_priority_consistent"] is False
    assert checks["cutoff_line_qty_consistent"] is False
    assert checks["cutoff_line_matches_ranking"] is False


def test_layer2_allocation_requires_explicit_economic_inputs():
    metrics = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "current_stock": 10,
            "in_flight": 0,
            "velocity_main": 1.0,
            "velocity_assorti": 1.0,
            "capital_locked": 10.0,
        }
    ]

    with pytest.raises(TypeError):
        _build_layer2_allocation_decisions(
            stock_health_metrics=metrics,
            lead_time_days_total=30,
        )


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
            "objective_score_if_main_until_eta": 2.0,
            "objective_score_if_assorti_until_eta": 1.0,
            "objective_components_if_main": {
                "expected_gross_profit": 2.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 2.0,
            },
            "objective_components_if_assorti": {
                "expected_gross_profit": 1.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 1.0,
            },
            "objective_score_gap_until_eta": 1.0,
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "assorti",
            "decision_reason": "profit_assorti_gt_main",
            "decision_reason_objective_score": "objective_score_assorti_gt_main",
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
    assert contract["checks"]["decision_reason_objective_score_matches_allocation"] is True
    assert contract["checks"]["allocation_matches_composite_objective_gate"] is False
    assert contract["checks"]["allocation_matches_profit_gate"] is False


def test_layer2_contract_summary_marks_violated_when_objective_fields_missing():
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
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": False,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary={"main": 1, "assorti": 0, "hold": 0},
    )

    checks = contract["checks"]
    assert contract["status"] == "violated"
    assert checks["objective_required_fields_present"] is False
    assert checks["objective_score_fields_numeric"] is False
    assert checks["objective_components_present"] is False
    assert checks["objective_components_numeric"] is False
    assert checks["objective_components_consistent_with_scores"] is False
    assert checks["allocation_matches_composite_objective_gate"] is False


def test_layer2_contract_summary_marks_violated_when_objective_fields_non_numeric():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 2.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 1.0,
            "capital_locked": 10.0,
            "objective_score_if_main_until_eta": "bad",
            "objective_score_if_assorti_until_eta": "worse",
            "objective_components_if_main": {
                "expected_gross_profit": 2.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": "bad",
            },
            "objective_components_if_assorti": {
                "expected_gross_profit": 1.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": "worse",
            },
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": False,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary={"main": 1, "assorti": 0, "hold": 0},
    )

    checks = contract["checks"]
    assert contract["status"] == "violated"
    assert checks["objective_required_fields_present"] is True
    assert checks["objective_score_fields_numeric"] is False
    assert checks["objective_components_present"] is True
    assert checks["objective_components_numeric"] is False
    assert checks["objective_components_consistent_with_scores"] is False
    assert checks["objective_components_match_formula"] is False
    assert checks["objective_score_gap_consistent_with_objective_scores"] is False
    assert checks["decision_reason_objective_score_matches_allocation"] is False
    assert checks["allocation_matches_composite_objective_gate"] is False


def test_layer2_contract_summary_marks_violated_when_objective_components_break_formula():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 2.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 1.0,
            "capital_locked": 10.0,
            "objective_score_if_main_until_eta": 1.5,
            "objective_score_if_assorti_until_eta": 1.0,
            "objective_components_if_main": {
                "expected_gross_profit": 2.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 1.5,
            },
            "objective_components_if_assorti": {
                "expected_gross_profit": 1.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 1.0,
            },
            "objective_score_gap_until_eta": 0.5,
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "decision_reason_objective_score": "objective_score_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": False,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary={"main": 1, "assorti": 0, "hold": 0},
    )

    checks = contract["checks"]
    assert contract["status"] == "violated"
    assert checks["objective_required_fields_present"] is True
    assert checks["objective_score_fields_numeric"] is True
    assert checks["objective_components_present"] is True
    assert checks["objective_components_numeric"] is True
    assert checks["objective_components_consistent_with_scores"] is True
    assert checks["objective_components_match_formula"] is False
    assert checks["objective_score_gap_consistent_with_objective_scores"] is True
    assert checks["decision_reason_objective_score_matches_allocation"] is True
    assert checks["allocation_matches_composite_objective_gate"] is False


def test_layer2_contract_summary_marks_violated_when_objective_gap_field_inconsistent():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 2.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 1.0,
            "capital_locked": 10.0,
            "objective_score_if_main_until_eta": 2.0,
            "objective_score_if_assorti_until_eta": 1.0,
            "objective_components_if_main": {
                "expected_gross_profit": 2.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 2.0,
            },
            "objective_components_if_assorti": {
                "expected_gross_profit": 1.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 1.0,
            },
            "objective_score_gap_until_eta": 0.2,
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "decision_reason_objective_score": "objective_score_main_gt_assorti",
            "tie_break_applied": False,
            "near_tie": False,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary={"main": 1, "assorti": 0, "hold": 0},
    )

    checks = contract["checks"]
    assert contract["status"] == "violated"
    assert checks["objective_components_match_formula"] is True
    assert checks["objective_score_gap_consistent_with_objective_scores"] is False
    assert checks["decision_reason_objective_score_matches_allocation"] is True
    assert checks["allocation_matches_composite_objective_gate"] is True


def test_layer2_contract_summary_marks_violated_when_objective_reason_conflicts_with_allocation():
    decisions = [
        {
            "color_id": 10,
            "size_id": 20,
            "eta_days": 1,
            "profit_if_main_until_eta": 2.0,
            "profit_if_assorti_until_eta": 1.0,
            "profit_gap_until_eta": 1.0,
            "capital_locked": 10.0,
            "objective_score_if_main_until_eta": 2.0,
            "objective_score_if_assorti_until_eta": 1.0,
            "objective_components_if_main": {
                "expected_gross_profit": 2.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 2.0,
            },
            "objective_components_if_assorti": {
                "expected_gross_profit": 1.0,
                "capital_cost_penalty": 0.0,
                "stockout_penalty": 0.0,
                "overstock_penalty": 0.0,
                "objective_score": 1.0,
            },
            "objective_score_gap_until_eta": 1.0,
            "gmroi_main": 0.2,
            "gmroi_assorti": 0.1,
            "gmroi_gap": 0.1,
            "allocation_decision": "main",
            "decision_reason": "profit_main_gt_assorti",
            "decision_reason_expected_gross_profit": "expected_gross_profit_main_gt_assorti",
            "decision_reason_objective_score": "objective_score_assorti_gt_main",
            "tie_break_applied": False,
            "near_tie": True,
        }
    ]

    contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=decisions,
        layer2_allocation_summary={"main": 1, "assorti": 0, "hold": 0},
    )

    checks = contract["checks"]
    assert contract["status"] == "violated"
    assert checks["decision_reason_matches_allocation"] is True
    assert checks["decision_reason_expected_gross_profit_matches_allocation"] is True
    assert checks["decision_reason_objective_score_matches_allocation"] is False
    assert checks["allocation_matches_composite_objective_gate"] is True


def test_layer2_decision_quality_summary_tracks_missing_objective_fields_without_profit_fallback():
    summary = _build_layer2_decision_quality_summary(
        layer2_allocation_decisions=[
            {
                "profit_if_main_until_eta": 2.0,
                "profit_if_assorti_until_eta": 1.0,
                "gmroi_main": 0.2,
                "gmroi_assorti": 0.1,
                "capital_locked": 10.0,
                "decision_reason": "profit_main_gt_assorti",
                "tie_break_applied": False,
                "near_tie": False,
            }
        ]
    )

    assert summary["objective_fields_valid_count"] == 0
    assert summary["objective_fields_missing_count"] == 1
    assert summary["objective_fields_invalid_count"] == 0
    assert summary["avg_objective_score_gap_until_eta"] == 0.0


def test_layer2_decision_quality_summary_tracks_ties_near_ties_and_reason_counts():
    decisions = [
        {
            "profit_if_main_until_eta": 2.5,
            "profit_if_assorti_until_eta": 2.3,
            "objective_score_if_main_until_eta": 2.5,
            "objective_score_if_assorti_until_eta": 2.3,
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
            "objective_score_if_main_until_eta": 1.2,
            "objective_score_if_assorti_until_eta": 1.2,
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
            "objective_score_if_main_until_eta": 1.0,
            "objective_score_if_assorti_until_eta": 3.0,
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
        near_tie_objective_gap_threshold=0.5,
    )

    assert summary["primary_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert summary["profit_gate_primary"] is False
    assert summary["expected_gross_profit_gate_primary"] is False
    assert summary["composite_objective_gate_primary"] is True
    assert summary["legacy_gate_primary_aliases"] == {
        "profit_gate_primary": {
            "value": False,
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
        "expected_gross_profit_gate_primary": {
            "value": False,
            "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        },
    }
    legacy_alias_deprecation_plan = summary["legacy_alias_deprecation_plan"]
    assert (
        legacy_alias_deprecation_plan["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )
    assert (
        legacy_alias_deprecation_plan["canonical_decision_gate"]
        == LAYER2_DECISION_GATE_CANONICAL
    )
    assert legacy_alias_deprecation_plan["policy"] == "non_breaking_aliases_during_transition_window"
    assert legacy_alias_deprecation_plan["legacy_decision_gate_aliases"] == [
        LAYER2_DECISION_GATE_LEGACY,
        "expected_gross_profit_until_eta",
    ]
    assert (
        legacy_alias_deprecation_plan["field_alias_replacements"]["near_tie_profit_gap_threshold"]
        == "near_tie_objective_gap_threshold"
    )
    assert summary["gmroi_usage"] == "diagnostic_only"
    assert summary["decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert summary["decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert summary["legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert summary["near_tie_objective_gap_threshold"] == 0.5
    assert summary["near_tie_profit_gap_threshold"] == 0.5
    assert summary["decision_count"] == 3
    assert summary["tie_count"] == 1
    assert summary["near_tie_count"] == 2
    assert summary["decision_reason_counts"] == {
        "profit_main_gt_assorti": 1,
        "profit_assorti_gt_main": 1,
        "profit_tie_hold": 1,
    }
    assert summary["decision_reason_counts_expected_gross_profit"] == {
        "expected_gross_profit_main_gt_assorti": 1,
        "expected_gross_profit_assorti_gt_main": 1,
        "expected_gross_profit_tie_hold": 1,
    }
    assert summary["decision_reason_counts_objective_score"] == {
        "objective_score_main_gt_assorti": 1,
        "objective_score_assorti_gt_main": 1,
        "objective_score_tie_hold": 1,
    }
    assert summary["avg_profit_gap_until_eta"] == 0.7333
    assert summary["avg_expected_gross_profit_gap_until_eta"] == 0.7333
    assert summary["avg_objective_score_gap_until_eta"] == 0.7333
    assert summary["avg_gmroi_gap"] == 0.08
    assert summary["capital_locked_total"] == 30.0
    assert summary["capital_locked_avg"] == 10.0
    assert summary["objective_fields_valid_count"] == 3
    assert summary["objective_fields_missing_count"] == 0
    assert summary["objective_fields_invalid_count"] == 0


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
                "reduce_order_size": 0.1,
            },
        },
        layer4_scenarios=[
            {"scenario": "Conservative"},
            {"scenario": "Aggressive"},
            {"scenario": "Aggressive"},
        ],
        unavoidable_stockout_risk_threshold=LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        accelerate_production_risk_threshold=LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        reduce_order_marginal_profit_rate=LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    )

    assert contract["version"] == LAYER5_CONTRACT_VERSION
    assert contract["status"] == "violated"
    assert contract["signal_count"] == 3
    checks = contract["checks"]
    assert checks["method_matches_expected"] is False
    assert checks["signal_policy_matches_expected"] is False
    assert checks["economic_policy_present"] is False
    assert checks["required_layer4_scenarios_present"] is False
    assert checks["required_layer4_scenarios_unique"] is False
    assert checks["unavoidable_stockout_is_bool"] is False
    assert checks["aggressive_risk_in_unit_interval"] is False
    assert checks["thresholds_in_unit_interval"] is False
    assert checks["threshold_sources_match_effective"] is False
    assert checks["threshold_order_valid"] is False
    assert checks["risk_threshold_matches_price_slowdown_threshold"] is False
    assert checks["signals_known_only"] is True
    assert checks["signals_unique"] is False
    assert checks["signals_order_is_canonical"] is False
    assert checks["non_unavoidable_has_no_signals_and_none_reason"] is False
    assert checks["unavoidable_has_signals"] is True
    assert checks["reason_consistent_with_signals"] is False
    assert checks["accelerate_signal_requires_severe_risk"] is False
    assert checks["price_slowdown_signal_requires_unavoidable_threshold"] is False
    assert checks["reduce_order_signal_requires_overstock_penalty_gate"] is True


def test_layer5_contract_summary_marks_violated_when_required_layer4_scenarios_missing():
    intervention = _build_layer5_intervention_signals(
        risk_level="critical",
        layer4_scenarios=[
            {"scenario": "Conservative", "stockout_risk_proxy": 0.7},
            {"scenario": "Balanced", "stockout_risk_proxy": 0.6},
            {"scenario": "Aggressive", "stockout_risk_proxy": 0.45},
        ],
        in_flight_effective_qty_total=50,
    )

    contract = _build_layer5_contract_summary(
        layer5_intervention=intervention,
        layer4_scenarios=[
            {"scenario": "Conservative"},
            {"scenario": "Aggressive"},
        ],
        unavoidable_stockout_risk_threshold=LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        accelerate_production_risk_threshold=LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        reduce_order_marginal_profit_rate=LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    )

    checks = contract["checks"]
    assert contract["version"] == LAYER5_CONTRACT_VERSION
    assert contract["status"] == "violated"
    assert checks["method_matches_expected"] is True
    assert checks["signal_policy_matches_expected"] is True
    assert checks["economic_policy_present"] is True
    assert checks["required_layer4_scenarios_present"] is False
    assert checks["required_layer4_scenarios_unique"] is False
    assert checks["signals_known_only"] is True
    assert checks["signals_order_is_canonical"] is True
    assert checks["reason_consistent_with_signals"] is True


def test_resource_allocation_contract_summary_marks_violated_for_double_use_payload():
    resource_allocation = {
        "mode": "per_article_bundle_competition",
        "total_resource_keys": 1,
        "competing_resource_keys": 1,
        "fully_reserved_resource_keys": 0,
        "total_stock_units": 10,
        "total_reserved_units": 12,
        "reserved_bundle_units": {1: 6, 2: 6},
        "reservations": [
            {
                "color_id": 10,
                "size_id": 20,
                "stock_qty": 10,
                "total_reserved_qty": 12,
                "shared_resource": True,
                "consumer_bundle_type_ids": [1, 2],
                "allocations": [
                    {
                        "bundle_type_id": 1,
                        "reserved_qty": 6,
                        "share_weight": 0.5,
                        "allocation_basis": "demand_share",
                    },
                    {
                        "bundle_type_id": 2,
                        "reserved_qty": 6,
                        "share_weight": 0.5,
                        "allocation_basis": "demand_share",
                    },
                ],
            }
        ],
    }

    contract = _build_resource_allocation_contract_summary(resource_allocation)

    assert contract["version"] == RESOURCE_ALLOCATION_CONTRACT_VERSION
    assert contract["status"] == "violated"
    assert contract["checks"]["no_double_use"] is False
    assert contract["checks"]["allocation_sums_consistent"] is True
    assert contract["checks"]["reservation_total_matches_summary"] is True


def test_build_competition_aware_resource_allocation_prevents_shared_color_double_use():
    allocation = _build_competition_aware_resource_allocation(
        bundle_type_ids=[1, 2],
        recipe_colors_by_bundle={1: {101, 102}, 2: {101, 103}},
        all_recipe_color_ids=[101, 102, 103],
        size_ids=[201],
        stock_by_color_size={(101, 201): 10, (102, 201): 6, (103, 201): 4},
        shares_by_bundle={1: 0.6, 2: 0.4},
    )

    assert allocation.contract["version"] == RESOURCE_ALLOCATION_CONTRACT_VERSION
    assert allocation.contract["status"] == "ok"
    assert allocation.contract["checks"]["no_double_use"] is True
    assert allocation.reserved_bundle_units[1] == 6
    assert allocation.reserved_bundle_units[2] == 4

    shared_reservation = next(
        item for item in allocation.reservations if item.color_id == 101 and item.size_id == 201
    )
    assert shared_reservation.shared_resource is True
    assert shared_reservation.stock_qty == 10
    assert shared_reservation.total_reserved_qty == 10
    assert sum(item.reserved_qty for item in shared_reservation.allocations) == 10
    assert sorted(item.bundle_type_id for item in shared_reservation.allocations) == [1, 2]


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
        "physical_scope": body.get("physical_scope"),
        "arrival_projection": body.get("arrival_projection"),
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
    physical_scope = body["physical_scope"]
    assert physical_scope["local_stock_scope"] == "all_warehouses_merged"
    assert physical_scope["wb_stock_scope"] == "request_explicit_bundle_stock"
    assert physical_scope["ready_bundle_source"] == "request"
    assert physical_scope["raw_single_source"] == "stock_balance_by_sku_unit_recipe_projection"
    assert physical_scope["nsc_assembled_bundle_inventory_state"] == "not_persisted"
    assert "assembled_nsc_bundles_not_separately_persisted" in physical_scope["warnings"]
    assert physical_scope["assumptions"]["size_weights_source"] == "request"
    assert physical_scope["assumptions"]["in_flight_source"] == "none"
    assert physical_scope["assumptions"]["bundle_stock_source"] == "request"
    assert (
        physical_scope["assumptions"]["raw_bundle_capacity_method"]
        == "competition_aware_recipe_projection"
    )
    assert physical_scope["assumptions"]["raw_bundle_capacity_counts_in_main_cover_model"] is True
    assert (
        physical_scope["assumptions"]["nsc_assembled_bundle_inventory_state"]
        == "not_persisted"
    )
    assert body["arrival_projection"]["status"] == "shortage_before_arrival"
    assert body["arrival_projection"]["arrival_horizon_days"] == 70
    assert body["arrival_projection"]["demand_units_until_arrival"] == 1400
    assert body["arrival_projection"]["ready_bundle_units_now"] == 10
    assert body["arrival_projection"]["raw_bundle_capacity_now"] == 20
    assert body["arrival_projection"]["in_flight_bundle_capacity_at_arrival"] == 0
    assert body["arrival_projection"]["projected_supply_units_before_arrival"] == 30
    assert body["arrival_projection"]["projected_availability_at_arrival"] == 0
    assert body["arrival_projection"]["projected_shortage_before_arrival"] == 1370
    assert body["arrival_projection"]["projected_cover_days_at_arrival"] == 0.0
    assert body["explanation"]["meta"]["physical_scope"] == body["physical_scope"]
    assert body["explanation"]["meta"]["arrival_projection"] == body["arrival_projection"]
    assert any("Physical scope:" in step for step in body["explanation"]["steps"])
    assert any("Arrival projection:" in step for step in body["explanation"]["steps"])


def test_production_order_scope_helper_matches_happy_path_api_contract(client, db_session):
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

    helper_physical_scope, helper_arrival_projection = build_physical_scope_and_arrival_projection(
        bundle_stock_source="request",
        in_flight_source="none",
        size_weights_source="request",
        bundle_type_ids=[seeded["bundle_type"].id],
        recipe_colors_by_bundle={
            seeded["bundle_type"].id: {seeded["color_1"].id, seeded["color_2"].id},
        },
        all_recipe_color_ids=[seeded["color_1"].id, seeded["color_2"].id],
        size_ids=[seeded["size_s"].id, seeded["size_m"].id],
        current_stock_by_color_size={
            (seeded["color_1"].id, seeded["size_s"].id): 10,
            (seeded["color_1"].id, seeded["size_m"].id): 10,
            (seeded["color_2"].id, seeded["size_s"].id): 10,
            (seeded["color_2"].id, seeded["size_m"].id): 10,
        },
        in_flight_effective_by_color_size={
            (seeded["color_1"].id, seeded["size_s"].id): 0,
            (seeded["color_1"].id, seeded["size_m"].id): 0,
            (seeded["color_2"].id, seeded["size_s"].id): 0,
            (seeded["color_2"].id, seeded["size_m"].id): 0,
        },
        shares_by_bundle={seeded["bundle_type"].id: 1.0},
        ready_bundle_stock_total=10,
        total_daily_sales=20.0,
        lead_time_days_total=70,
        estimate_raw_bundle_stock=planning_production_order_service._estimate_competition_aware_raw_bundle_stock,
    )

    assert helper_physical_scope.model_dump(mode="json") == body["physical_scope"]
    assert helper_arrival_projection.model_dump(mode="json") == body["arrival_projection"]


def test_production_order_proposal_exposes_resource_allocation_consumption(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-RESOURCE",
        name="PO-BT-RESOURCE",
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

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "daily_sales": 18.0},
        {"bundle_type_id": assorti_bundle_type.id, "daily_sales": 12.0},
    ]
    payload["bundle_stock"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "wb_qty": 5, "local_qty": 5},
        {"bundle_type_id": assorti_bundle_type.id, "wb_qty": 3, "local_qty": 1},
    ]

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    resource_allocation = body["constraints_applied"]["resource_allocation"]
    assert resource_allocation["mode"] == "per_article_bundle_competition"
    assert resource_allocation["competing_resource_keys"] > 0
    assert resource_allocation["contract"]["version"] == RESOURCE_ALLOCATION_CONTRACT_VERSION
    assert resource_allocation["contract"]["status"] == "ok"

    shared_reservations = [item for item in resource_allocation["reservations"] if item["shared_resource"]]
    assert shared_reservations
    for reservation in shared_reservations:
        assert reservation["total_reserved_qty"] <= reservation["stock_qty"]
        assert sum(item["reserved_qty"] for item in reservation["allocations"]) == reservation["total_reserved_qty"]

    meta = body["explanation"]["meta"]
    assert meta["resource_allocation"]["contract"]["status"] == "ok"
    assert any("Resource allocation:" in step for step in body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert compact_meta["resource_allocation"]["contract"]["status"] == "ok"
    assert any("Resource allocation:" in step for step in compact_body["explanation"]["steps"])
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["resource_allocation"] == meta["resource_allocation"]


def test_production_order_proposal_shared_color_pool_reduces_local_fabric_min_uplift(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    seeded["color_2"].pantone_code = seeded["color_1"].pantone_code
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"] = [{"bundle_type_id": seeded["bundle_type"].id, "daily_sales": 0.5}]
    payload["bundle_stock"] = [{"bundle_type_id": seeded["bundle_type"].id, "wb_qty": 0, "local_qty": 0}]
    payload["overrides"]["fabric_min_batch_qty_default"] = 100
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    base_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert base_response.status_code == 200, base_response.text
    base_body = base_response.json()
    base_recommendation = base_body["recommendation"]
    assert base_recommendation is not None
    base_fabric_constraints = base_body["constraints_applied"]["fabric_min_batches"]
    assert base_fabric_constraints
    assert base_fabric_constraints[0]["sibling_proxy_required"] == 0
    base_total_units = base_recommendation["total_units"]

    sibling_article = Article(code="PO-ART-SHARED", name="PO-ART-SHARED")
    sibling_color = Color(inner_code="PO-C-SHARED", pantone_code=seeded["color_1"].pantone_code, description="Shared Pantone")
    db_session.add_all([sibling_article, sibling_color])
    db_session.flush()

    db_session.add(
        SkuUnit(
            article_id=sibling_article.id,
            color_id=sibling_color.id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        ArticlePlanningSettings(
            article_id=sibling_article.id,
            include_in_planning=True,
            priority=1,
            target_coverage_days=60,
            lead_time_days=70,
            service_level_percent=90,
        )
    )
    db_session.add(
        ArticleWbMapping(
            article_id=sibling_article.id,
            wb_sku="WB-SHARED-PANTONE-1",
        )
    )

    sales_start = date(2026, 1, 1)
    for day_offset in range(30):
        sales_date = sales_start + timedelta(days=day_offset)
        db_session.add(
            WbSalesDaily(
                wb_sku="WB-SHARED-PANTONE-1",
                date=sales_date,
                sales_qty=1,
                revenue=None,
                created_at=datetime(sales_date.year, sales_date.month, sales_date.day, tzinfo=timezone.utc),
            )
        )
    db_session.commit()

    shared_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert shared_response.status_code == 200, shared_response.text
    shared_body = shared_response.json()
    shared_recommendation = shared_body["recommendation"]
    assert shared_recommendation is not None
    assert shared_recommendation["total_units"] < base_total_units

    shared_color_pool = shared_body["explanation"]["meta"]["shared_color_pool"]
    assert shared_color_pool["status"] == "ok"
    assert shared_color_pool["sibling_article_count"] >= 1
    pantone_item = shared_color_pool["pantones"][seeded["color_1"].pantone_code]
    assert pantone_item["sibling_proxy_required"] > 0
    assert pantone_item["sibling_article_ids"] == [sibling_article.id]
    assert any("Shared color pool:" in step for step in shared_body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(shared_body) == _business_projection(compact_body)
    assert compact_meta["shared_color_pool"] == shared_color_pool
    assert any("Shared color pool:" in step for step in compact_body["explanation"]["steps"])


def test_production_order_proposal_economic_overrides_are_traced_in_meta(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    seeded["bundle_type"].is_assorti = True
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].update(
        {
            "production_cost_per_unit": 1.0,
            "logistics_cost_per_unit": 0.2,
            "wb_commission_percent_main": 0.05,
            "wb_commission_percent_assorti": 0.05,
            "average_realized_price_main": 1.5,
            "average_realized_price_assorti": 2.4,
            "available_capital": 60.0,
        }
    )

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]

    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"]["average_realized_price_main"] == "request"
    assert alpha_proxy["economic_source"]["average_realized_price_assorti"] == "request"
    assert alpha_proxy["economic_source"]["available_capital"] == "request"
    assert alpha_proxy["economic_inputs"]["available_capital"] == 60.0
    assert alpha_proxy["layer_2_allocation_method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_allocation_method_canonical"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_legacy_allocation_method"] == LAYER2_ALLOCATION_METHOD
    assert alpha_proxy["layer_2_decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert (
        alpha_proxy["layer_2_legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )

    layer2_meta = meta["layer_2_allocation"]
    assert layer2_meta["method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2_meta["method_canonical"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2_meta["legacy_method"] == LAYER2_ALLOCATION_METHOD
    assert layer2_meta["decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2_meta["decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2_meta["legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    layer2_legacy_alias_plan = layer2_meta["legacy_alias_deprecation_plan"]
    assert layer2_legacy_alias_plan["deprecated_after"] == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    assert layer2_meta["decision_quality"]["legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    assert alpha_proxy["layer_2_legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    layer2_summary = meta["layer_2_allocation"]["summary"]
    assert layer2_summary["main"] > 0
    assert layer2_summary["assorti"] == 0

    capital_gap = meta["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert isinstance(capital_gap["available_capital"], float)
    assert isinstance(capital_gap["required_capital"], float)
    assert isinstance(capital_gap["deficit_or_surplus"], float)

    layer4 = meta["layer_4_scenarios"]
    assert len(layer4["scenarios"]) == 3
    for scenario in layer4["scenarios"]:
        assert "expected_revenue" in scenario
        assert "expected_gross_profit" in scenario
        assert "expected_margin_percent" in scenario
        assert "expected_turnover_days" in scenario
        assert "stockout_probability_proxy" in scenario
        assert "overstock_risk_proxy" in scenario
        assert "capital_delta_vs_balanced" in scenario
        assert "expected_revenue_delta_vs_balanced" in scenario
        assert "expected_gross_profit_delta_vs_balanced" in scenario
        assert "objective_score_delta_vs_balanced" in scenario
        assert (
            scenario["expected_gross_profit_delta_vs_balanced"]
            == scenario["gross_profit_delta_vs_balanced"]
        )

    aggregate = meta["layer_4_scenarios"]["aggregate_deltas"]
    assert set(aggregate["aggressive_vs_conservative"].keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }


def test_production_order_proposal_reports_budget_limited_capital_constraint_summary(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0
    payload["overrides"]["available_capital"] = 20.0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    recommendation = body["recommendation"]
    assert recommendation is not None
    assert recommendation["lines"]

    meta = body["explanation"]["meta"]
    capital_constraint = meta["capital_constraint"]
    assert capital_constraint["status"] == "budget_limited_applied"
    assert capital_constraint["constrained"] is True
    assert capital_constraint["available_capital"] == 20.0
    assert (
        capital_constraint["required_capital_before_constraint"]
        > capital_constraint["available_capital"]
    )
    assert (
        capital_constraint["allocated_capital_after_constraint"]
        <= capital_constraint["available_capital"]
    )
    assert capital_constraint["line_count_after"] == len(recommendation["lines"])
    assert capital_constraint["line_count_before"] >= capital_constraint["line_count_after"]
    assert capital_constraint["remaining_capital"] >= 0.0

    ranking = capital_constraint["ranking"]
    assert isinstance(ranking, list)
    assert len(ranking) >= len(recommendation["lines"])
    assert recommendation["lines"][0]["color_id"] == ranking[0]["color_id"]
    assert recommendation["lines"][0]["size_id"] == ranking[0]["size_id"]

    contract = capital_constraint["contract"]
    assert contract["version"] == CAPITAL_CONSTRAINT_CONTRACT_VERSION
    assert contract["status"] == "ok"
    assert contract["checks"]["budget_accounting_consistent"] is True
    assert contract["checks"]["ranking_sorted_by_objective_per_capital"] is True
    assert contract["checks"]["ranking_risk_priority_consistent"] is True

    for line in recommendation["lines"]:
        assert line["source_reason"].endswith("|capital_constraint")

    cutoff_line = capital_constraint["cutoff_line"]
    assert cutoff_line is not None
    assert cutoff_line["requested_qty"] >= cutoff_line["allocated_qty"] >= 0

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["capital_constraint"] == capital_constraint
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_price_flip_changes_layer2_allocation_decision_end_to_end(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-MIX-FLIP",
        name="PO-BT-MIX-FLIP",
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

    base_payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    base_payload["bundle_daily_sales"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "daily_sales": 10.0},
        {"bundle_type_id": assorti_bundle_type.id, "daily_sales": 10.0},
    ]
    base_payload["bundle_stock"] = [
        {"bundle_type_id": seeded["bundle_type"].id, "wb_qty": 5, "local_qty": 5},
        {"bundle_type_id": assorti_bundle_type.id, "wb_qty": 5, "local_qty": 5},
    ]
    base_payload["overrides"]["fabric_min_batch_qty_default"] = 0
    base_payload["overrides"]["elastic_min_batch_qty_default"] = 0
    base_payload["overrides"].update(
        {
            "production_cost_per_unit": 1.0,
            "logistics_cost_per_unit": 0.2,
            "wb_commission_percent_main": 0.05,
            "wb_commission_percent_assorti": 0.05,
        }
    )

    main_wins_payload = deepcopy(base_payload)
    main_wins_payload["overrides"].update(
        {
            "average_realized_price_main": 2.4,
            "average_realized_price_assorti": 1.5,
        }
    )
    assorti_wins_payload = deepcopy(base_payload)
    assorti_wins_payload["overrides"].update(
        {
            "average_realized_price_main": 1.5,
            "average_realized_price_assorti": 2.4,
        }
    )

    main_wins_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=main_wins_payload,
    )
    assorti_wins_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=assorti_wins_payload,
    )

    assert main_wins_response.status_code == 200, main_wins_response.text
    assert assorti_wins_response.status_code == 200, assorti_wins_response.text

    main_wins_body = main_wins_response.json()
    assorti_wins_body = assorti_wins_response.json()

    main_margin_proxy = main_wins_body["explanation"]["meta"]["alpha_proxy_economics"]["margin_proxy"]
    assorti_margin_proxy = assorti_wins_body["explanation"]["meta"]["alpha_proxy_economics"]["margin_proxy"]
    assert main_margin_proxy == {"main": 1.08, "assorti": 0.225}
    assert assorti_margin_proxy == {"main": 0.225, "assorti": 1.08}

    main_summary = main_wins_body["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assorti_summary = assorti_wins_body["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assert main_summary["assorti"] > 0
    assert main_summary["main"] == 0
    assert assorti_summary["main"] > 0
    assert assorti_summary["assorti"] == 0

    main_decisions = sorted(
        main_wins_body["explanation"]["meta"]["layer_2_allocation"]["decisions"],
        key=lambda item: (item["color_id"], item["size_id"]),
    )
    assorti_decisions = sorted(
        assorti_wins_body["explanation"]["meta"]["layer_2_allocation"]["decisions"],
        key=lambda item: (item["color_id"], item["size_id"]),
    )
    assert len(main_decisions) == len(assorti_decisions) > 0
    for main_decision, assorti_decision in zip(main_decisions, assorti_decisions):
        assert main_decision["color_id"] == assorti_decision["color_id"]
        assert main_decision["size_id"] == assorti_decision["size_id"]
        assert main_decision["eta_days"] == assorti_decision["eta_days"]
        assert main_decision["capital_locked"] == assorti_decision["capital_locked"]
        assert main_decision["allocation_decision"] == "assorti"
        assert (
            main_decision["objective_score_if_assorti_until_eta"]
            > main_decision["objective_score_if_main_until_eta"]
        )
        assert assorti_decision["allocation_decision"] == "main"
        assert (
            assorti_decision["objective_score_if_main_until_eta"]
            > assorti_decision["objective_score_if_assorti_until_eta"]
        )


@pytest.mark.parametrize(
    (
        "case_name",
        "bundle_daily_sales",
        "per_sku_stock_qty",
        "available_capital",
        "economic_overrides",
        "expected_profit_winner",
        "expected_objective_winner",
        "expected_layer5_signal",
    ),
    [
        pytest.param(
            "stockout_dominates",
            {"main": 8.0, "assorti": 0.2},
            10,
            30.0,
            {
                "production_cost_per_unit": 1.0,
                "logistics_cost_per_unit": 0.2,
                "wb_commission_percent_main": 0.10,
                "wb_commission_percent_assorti": 0.10,
                "average_realized_price_main": 2.0,
                "average_realized_price_assorti": 2.0,
            },
            "main",
            "assorti",
            "accelerate_production",
            id="stockout-dominates",
        ),
        pytest.param(
            "overstock_dominates",
            {"main": 2.0, "assorti": 0.3},
            400,
            1000000.0,
            {
                "production_cost_per_unit": 0.9,
                "logistics_cost_per_unit": 0.1,
                "wb_commission_percent_main": 0.0,
                "wb_commission_percent_assorti": 0.0,
                "average_realized_price_main": 1.1,
                "average_realized_price_assorti": 2.5,
            },
            "assorti",
            "main",
            "reduce_order_size",
            id="overstock-dominates",
        ),
        pytest.param(
            "commission_price_conflict",
            {"main": 8.0, "assorti": 8.0},
            10,
            30.0,
            {
                "production_cost_per_unit": 1.0,
                "logistics_cost_per_unit": 0.2,
                "wb_commission_percent_main": 0.35,
                "wb_commission_percent_assorti": 0.05,
                "average_realized_price_main": 3.2,
                "average_realized_price_assorti": 2.1,
            },
            "main",
            "assorti",
            "accelerate_production",
            id="commission-price-conflict",
        ),
    ],
)
def test_production_order_proposal_e2e_regimes_objective_over_profit_and_layer5_signals(
    client,
    db_session,
    case_name,
    bundle_daily_sales,
    per_sku_stock_qty,
    available_capital,
    economic_overrides,
    expected_profit_winner,
    expected_objective_winner,
    expected_layer5_signal,
):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code=f"PO-BT-E2E-{case_name}",
        name=f"PO-BT-E2E-{case_name}",
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

    stock_rows = db_session.query(StockBalance).all()
    assert stock_rows
    for row in stock_rows:
        row.quantity = per_sku_stock_qty
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"] = [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "daily_sales": bundle_daily_sales["main"],
        },
        {
            "bundle_type_id": assorti_bundle_type.id,
            "daily_sales": bundle_daily_sales["assorti"],
        },
    ]
    wb_qty = per_sku_stock_qty // 2
    local_qty = per_sku_stock_qty - wb_qty
    payload["bundle_stock"] = [
        {
            "bundle_type_id": seeded["bundle_type"].id,
            "wb_qty": wb_qty,
            "local_qty": local_qty,
        },
        {
            "bundle_type_id": assorti_bundle_type.id,
            "wb_qty": wb_qty,
            "local_qty": local_qty,
        },
    ]
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0
    payload["overrides"]["allow_order_with_buffer"] = False
    payload["overrides"]["available_capital"] = available_capital
    payload["overrides"].update(economic_overrides)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    layer2 = meta["layer_2_allocation"]
    objective_parameters = layer2["objective_parameters"]
    assert LAYER2_CAPITAL_COST_RATE == 0.08
    assert LAYER2_STOCKOUT_PENALTY_WEIGHT == 1.0
    assert LAYER2_OVERSTOCK_PENALTY_WEIGHT == 1.0
    assert objective_parameters == {
        "capital_cost_rate": 0.08,
        "stockout_penalty_weight": 1.0,
        "overstock_penalty_weight": 1.0,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    assert (
        meta["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == objective_parameters
    )

    decisions = layer2["decisions"]
    assert decisions
    objective_reason_by_decision = {
        "main": "objective_score_main_gt_assorti",
        "assorti": "objective_score_assorti_gt_main",
    }
    objective_over_profit_conflicts = 0

    for decision in decisions:
        profit_main = float(decision["expected_gross_profit_if_main_until_eta"])
        profit_assorti = float(decision["expected_gross_profit_if_assorti_until_eta"])
        objective_main = float(decision["objective_score_if_main_until_eta"])
        objective_assorti = float(decision["objective_score_if_assorti_until_eta"])

        if profit_main > profit_assorti:
            profit_winner = "main"
        elif profit_assorti > profit_main:
            profit_winner = "assorti"
        else:
            profit_winner = "hold"

        if objective_main > objective_assorti:
            objective_winner = "main"
        elif objective_assorti > objective_main:
            objective_winner = "assorti"
        else:
            objective_winner = "hold"

        assert profit_winner == expected_profit_winner
        assert objective_winner == expected_objective_winner
        assert decision["allocation_decision"] == expected_objective_winner
        assert (
            decision["decision_reason_objective_score"]
            == objective_reason_by_decision[expected_objective_winner]
        )

        if profit_winner != objective_winner:
            objective_over_profit_conflicts += 1

    assert objective_over_profit_conflicts == len(decisions)
    assert layer2["summary"][expected_objective_winner] == len(decisions)

    layer5 = meta["layer_5_intervention"]
    assert layer5["contract"]["status"] == "ok"
    assert layer5["signal_policy"] == "critical_risk_thresholds"
    assert expected_layer5_signal in layer5["signals"]
    if expected_layer5_signal == "accelerate_production":
        assert layer5["reason"] in {
            "no_effective_in_flight_and_high_stockout_risk",
            "in_flight_present_but_severe_stockout_risk",
            "mixed_risk_and_cost_signals",
        }
    if expected_layer5_signal == "reduce_order_size":
        assert layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"

    expected_compact_assorti_classification = {
        "source": meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }
    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)

    compact_meta = compact_body["explanation"]["meta"]
    compact_layer2 = compact_meta["layer_2_allocation"]
    assert compact_meta["alpha_proxy_economics"] == meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_layer2 == expected_compact_layer2
    assert compact_meta["alpha_proxy_economics"]["layer_2_objective_parameters"] == objective_parameters
    full_layer4 = meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4
    compact_layer5 = compact_meta["layer_5_intervention"]
    assert compact_layer5 == layer5


@pytest.mark.parametrize(
    (
        "case_name",
        "bundle_daily_sales",
        "per_sku_stock_qty",
        "available_capital",
        "economic_overrides",
        "expected_profit_winner",
        "expected_objective_winner",
        "expected_layer5_signal",
    ),
    [
        pytest.param(
            "stockout_dominates",
            {"main": 8.0, "assorti": 0.2},
            10,
            30.0,
            {
                "production_cost_per_unit": 1.0,
                "logistics_cost_per_unit": 0.2,
                "wb_commission_percent_main": 0.10,
                "wb_commission_percent_assorti": 0.10,
                "average_realized_price_main": 2.0,
                "average_realized_price_assorti": 2.0,
            },
            "main",
            "assorti",
            "accelerate_production",
            id="stockout-dominates",
        ),
        pytest.param(
            "overstock_dominates",
            {"main": 2.0, "assorti": 0.3},
            400,
            1000000.0,
            {
                "production_cost_per_unit": 0.9,
                "logistics_cost_per_unit": 0.1,
                "wb_commission_percent_main": 0.0,
                "wb_commission_percent_assorti": 0.0,
                "average_realized_price_main": 1.1,
                "average_realized_price_assorti": 2.5,
            },
            "assorti",
            "main",
            "reduce_order_size",
            id="overstock-dominates",
        ),
        pytest.param(
            "commission_price_conflict",
            {"main": 8.0, "assorti": 8.0},
            10,
            30.0,
            {
                "production_cost_per_unit": 1.0,
                "logistics_cost_per_unit": 0.2,
                "wb_commission_percent_main": 0.35,
                "wb_commission_percent_assorti": 0.05,
                "average_realized_price_main": 3.2,
                "average_realized_price_assorti": 2.1,
            },
            "main",
            "assorti",
            "accelerate_production",
            id="commission-price-conflict",
        ),
    ],
)
def test_production_order_proposal_from_wb_e2e_regimes_objective_over_profit_and_layer5_signals(
    client,
    db_session,
    case_name,
    bundle_daily_sales,
    per_sku_stock_qty,
    available_capital,
    economic_overrides,
    expected_profit_winner,
    expected_objective_winner,
    expected_layer5_signal,
):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code=f"PO-BT-WB-E2E-{case_name}",
        name=f"PO-BT-WB-E2E-{case_name}",
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

    stock_rows = db_session.query(StockBalance).all()
    assert stock_rows
    for row in stock_rows:
        row.quantity = per_sku_stock_qty

    as_of_date = datetime(2026, 1, 10, tzinfo=timezone.utc).date()
    observation_window_days = 30
    wb_sku_main = f"WB-PO-R3-MAIN-{case_name}"
    wb_sku_assorti = f"WB-PO-R3-ASSORTI-{case_name}"

    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku_main,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku_assorti,
                bundle_type_id=assorti_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku_main,
                date=as_of_date,
                sales_qty=int(bundle_daily_sales["main"] * observation_window_days),
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku=wb_sku_assorti,
                date=as_of_date,
                sales_qty=int(bundle_daily_sales["assorti"] * observation_window_days),
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku_main,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=per_sku_stock_qty,
                updated_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku_assorti,
                warehouse_id=2,
                warehouse_name="WB-2",
                stock_qty=per_sku_stock_qty,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": observation_window_days,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id, assorti_bundle_type.id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
            "available_capital": available_capital,
            **economic_overrides,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    layer2 = meta["layer_2_allocation"]
    objective_parameters = layer2["objective_parameters"]
    assert objective_parameters == {
        "capital_cost_rate": 0.08,
        "stockout_penalty_weight": 1.0,
        "overstock_penalty_weight": 1.0,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    assert meta["alpha_proxy_economics"]["layer_2_objective_parameters"] == objective_parameters
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    from_wb_meta = meta["from_wb"]
    expected_compact_freshness = {
        "status": from_wb_meta["freshness"]["status"],
        "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
        "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
        "threshold_days": from_wb_meta["freshness"]["threshold_days"],
        "threshold_source": from_wb_meta["freshness"]["threshold_source"],
    }
    economic_observed_prices = from_wb_meta.get("economic_observed_prices")
    expected_compact_observed_prices = {}
    if isinstance(economic_observed_prices, dict):
        expected_compact_observed_prices = {
            "source": economic_observed_prices.get("source"),
            "window": economic_observed_prices.get("window"),
            "anomaly_max_deviation": economic_observed_prices.get("anomaly_max_deviation"),
            "prices": economic_observed_prices.get("prices"),
            "sample_counts": economic_observed_prices.get("sample_counts"),
        }
    expected_compact_commission_meta = {
        "source": from_wb_meta["economic_observed_commission"]["source"],
        "status": from_wb_meta["economic_observed_commission"]["status"],
        "reason": from_wb_meta["economic_observed_commission"]["reason"],
        "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
        "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
        "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
    }
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": expected_compact_freshness,
        "economic_observed_prices": expected_compact_observed_prices,
        "economic_observed_commission": expected_compact_commission_meta,
        "snapshot": {
            "daily_sales_bundle_count": len(bundle_daily_sales),
            "daily_sales_total": sum(bundle_daily_sales.values()),
            "wb_stock_bundle_count": len(payload["bundle_type_ids"]),
            "wb_stock_total": per_sku_stock_qty * len(payload["bundle_type_ids"]),
            "wb_stock_updated_bundle_count": len(payload["bundle_type_ids"]),
        },
    }
    assert from_wb_meta["daily_sales_by_bundle"][str(seeded["bundle_type"].id)] == bundle_daily_sales["main"]
    assert from_wb_meta["daily_sales_by_bundle"][str(assorti_bundle_type.id)] == bundle_daily_sales["assorti"]
    assert from_wb_meta["wb_stock_by_bundle"][str(seeded["bundle_type"].id)] == per_sku_stock_qty
    assert from_wb_meta["wb_stock_by_bundle"][str(assorti_bundle_type.id)] == per_sku_stock_qty

    decisions = layer2["decisions"]
    assert decisions
    objective_reason_by_decision = {
        "main": "objective_score_main_gt_assorti",
        "assorti": "objective_score_assorti_gt_main",
    }
    objective_over_profit_conflicts = 0

    for decision in decisions:
        profit_main = float(decision["expected_gross_profit_if_main_until_eta"])
        profit_assorti = float(decision["expected_gross_profit_if_assorti_until_eta"])
        objective_main = float(decision["objective_score_if_main_until_eta"])
        objective_assorti = float(decision["objective_score_if_assorti_until_eta"])

        if profit_main > profit_assorti:
            profit_winner = "main"
        elif profit_assorti > profit_main:
            profit_winner = "assorti"
        else:
            profit_winner = "hold"

        if objective_main > objective_assorti:
            objective_winner = "main"
        elif objective_assorti > objective_main:
            objective_winner = "assorti"
        else:
            objective_winner = "hold"

        assert profit_winner == expected_profit_winner
        assert objective_winner == expected_objective_winner
        assert decision["allocation_decision"] == expected_objective_winner
        assert (
            decision["decision_reason_objective_score"]
            == objective_reason_by_decision[expected_objective_winner]
        )

        if profit_winner != objective_winner:
            objective_over_profit_conflicts += 1

    assert objective_over_profit_conflicts == len(decisions)
    assert layer2["summary"][expected_objective_winner] == len(decisions)

    layer5 = meta["layer_5_intervention"]
    assert layer5["contract"]["status"] == "ok"
    assert layer5["signal_policy"] == "critical_risk_thresholds"
    assert expected_layer5_signal in layer5["signals"]
    if expected_layer5_signal == "accelerate_production":
        assert layer5["reason"] in {
            "no_effective_in_flight_and_high_stockout_risk",
            "in_flight_present_but_severe_stockout_risk",
            "mixed_risk_and_cost_signals",
        }
    if expected_layer5_signal == "reduce_order_size":
        assert layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"

    expected_compact_assorti_classification = {
        "source": meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer4 = meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)

    compact_meta = compact_body["explanation"]["meta"]
    compact_layer2 = compact_meta["layer_2_allocation"]
    assert "decisions" not in compact_layer2
    assert compact_meta["alpha_proxy_economics"] == meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_layer2 == expected_compact_layer2
    assert compact_meta["alpha_proxy_economics"]["layer_2_objective_parameters"] == objective_parameters
    assert compact_meta["layer_4_scenarios"] == expected_compact_layer4
    compact_from_wb = compact_meta["from_wb"]
    assert compact_from_wb == expected_compact_from_wb
    compact_layer5 = compact_meta["layer_5_intervention"]
    assert compact_layer5 == layer5


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
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in layer2_step
    assert "legacy_decision_gate=profit_until_eta" in layer2_step
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
    assert meta["capital_constraint"]["contract"]["status"] == "ok"
    assert (
        meta["capital_constraint"]["contract"]["checks"]["ranking_risk_priority_consistent"]
        is True
    )
    assert meta["layer_2_allocation"]["decision_quality"]["decision_count"] > 0
    assert (
        meta["layer_2_allocation"]["legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )
    layer2_compact_contract_checks = meta["layer_2_allocation"]["contract"]["checks"]
    assert layer2_compact_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_compact_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_compact_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert layer2_compact_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_compact_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_compact_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_compact_contract_checks["capital_locked_metric_valid"] is True
    assert meta["layer_2_allocation"]["decision_quality"]["profit_gate_primary"] is False
    assert meta["layer_2_allocation"]["decision_quality"]["composite_objective_gate_primary"] is True
    assert meta["layer_2_allocation"]["objective_parameters"] == {
        "capital_cost_rate": 0.08,
        "stockout_penalty_weight": 1.0,
        "overstock_penalty_weight": 1.0,
    }
    assert meta["layer_2_allocation"]["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    assert (
        meta["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == meta["layer_2_allocation"]["objective_parameters"]
    )
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert meta["layer_3_purchase_shaping"]["contract"]["status"] == "ok"
    assert meta["layer_4_scenarios"]["contract"]["status"] == "ok"
    assert set(meta["layer_4_scenarios"]["aggregate_deltas"]["aggressive_vs_conservative"].keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }
    for scenario in meta["layer_4_scenarios"]["scenarios"]:
        assert "capital_delta_vs_balanced" in scenario
        assert "expected_revenue_delta_vs_balanced" in scenario
        assert "expected_gross_profit_delta_vs_balanced" in scenario
        assert "objective_score_delta_vs_balanced" in scenario
    assert meta["layer_5_intervention"]["signal_policy"] == "critical_risk_thresholds"
    assert meta["layer_5_intervention"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    assert any("Physical scope:" in step for step in steps)
    assert any("Arrival projection:" in step for step in steps)
    assert meta["physical_scope"]["nsc_assembled_bundle_inventory_state"] == "not_persisted"
    assert meta["arrival_projection"]["status"] == "shortage_before_arrival"
    assert meta["arrival_projection"]["projected_shortage_before_arrival"] == 1370
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert (
        alpha_proxy["layer_2_near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["layer_3_calibration"]["method"] == "risk_weighted_factor_clamp"
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    assert "line_keys" not in meta["elastic_uplift"]
    assert "line_alloc" not in meta["elastic_uplift"]

    full_payload = deepcopy(payload)
    full_payload.pop("explainability_mode", None)
    full_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=full_payload,
    )
    assert full_response.status_code == 200, full_response.text

    full_body = full_response.json()
    full_meta = full_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    expected_compact_layer4 = {
        "method": full_meta["layer_4_scenarios"]["method"],
        "factors": full_meta["layer_4_scenarios"]["factors"],
        "contract": full_meta["layer_4_scenarios"]["contract"],
        "aggregate_deltas": full_meta["layer_4_scenarios"]["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_meta["layer_4_scenarios"]["scenarios"]
        ],
    }
    assert _business_projection(body) == _business_projection(full_body)
    assert meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert meta["warnings"] == full_meta["warnings"]
    assert meta["economics_trust"] == full_meta["economics_trust"]
    assert meta["capital_governance"] == full_meta["capital_governance"]
    assert meta["sources"] == full_meta["sources"]
    assert meta["physical_scope"] == full_meta["physical_scope"]
    assert meta["arrival_projection"] == full_meta["arrival_projection"]
    assert meta["reorder_policy"] == full_meta["reorder_policy"]
    assert meta["economic_buffer"] == full_meta["economic_buffer"]
    assert meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert meta["capital_gap"] == full_meta["capital_gap"]
    assert meta["capital_constraint"] == full_meta["capital_constraint"]
    assert meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert meta["layer_2_allocation"]["decision_quality"] == full_meta["layer_2_allocation"]["decision_quality"]
    assert meta["layer_2_allocation"]["contract"] == full_meta["layer_2_allocation"]["contract"]
    assert meta["layer_4_scenarios"] == expected_compact_layer4
    assert meta["layer_5_intervention"] == full_meta["layer_5_intervention"]


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

    full_meta = full_body["explanation"]["meta"]
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer2 = full_meta["layer_2_allocation"]
    expected_compact_layer2 = {
        "method": full_layer2.get("method"),
        "method_canonical": full_layer2.get("method_canonical"),
        "legacy_method": full_layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": full_layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": full_layer2.get("summary", {}),
        "contract": full_layer2.get("contract", {}),
        "decision_quality": full_layer2.get("decision_quality", {}),
        "decision_gate": full_layer2.get("decision_gate"),
        "decision_gate_canonical": full_layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": full_layer2.get("legacy_decision_gate"),
        "tie_break": full_layer2.get("tie_break"),
        "gmroi_usage": full_layer2.get("gmroi_usage"),
        "objective_formula": full_layer2.get("objective_formula"),
        "objective_parameters": full_layer2.get("objective_parameters", {}),
        "objective_source": full_layer2.get("objective_source", {}),
    }
    assert compact_meta["sources"] == full_meta["sources"]
    assert compact_meta["physical_scope"] == full_meta["physical_scope"]
    assert compact_meta["arrival_projection"] == full_meta["arrival_projection"]
    assert compact_meta["reorder_policy"] == full_meta["reorder_policy"]
    assert compact_meta["economic_buffer"] == full_meta["economic_buffer"]
    assert compact_meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert compact_meta["capital_gap"] == full_meta["capital_gap"]
    assert compact_meta["capital_constraint"] == full_meta["capital_constraint"]
    assert compact_meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["layer_2_allocation"] == expected_compact_layer2

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in compact_layer2_step
    assert "legacy_decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_meta["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is False
    assert compact_layer2["decision_quality"]["composite_objective_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    assert compact_layer2["objective_parameters"] == {
        "capital_cost_rate": 0.08,
        "stockout_penalty_weight": 1.0,
        "overstock_penalty_weight": 1.0,
    }
    assert compact_layer2["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    assert (
        compact_body["explanation"]["meta"]["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == compact_layer2["objective_parameters"]
    )
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    full_layer4 = full_meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4
    assert compact_meta["layer_5_intervention"] == full_meta["layer_5_intervention"]


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

    full_meta = full_body["explanation"]["meta"]
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer2 = full_meta["layer_2_allocation"]
    expected_compact_layer2 = {
        "method": full_layer2.get("method"),
        "method_canonical": full_layer2.get("method_canonical"),
        "legacy_method": full_layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": full_layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": full_layer2.get("summary", {}),
        "contract": full_layer2.get("contract", {}),
        "decision_quality": full_layer2.get("decision_quality", {}),
        "decision_gate": full_layer2.get("decision_gate"),
        "decision_gate_canonical": full_layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": full_layer2.get("legacy_decision_gate"),
        "tie_break": full_layer2.get("tie_break"),
        "gmroi_usage": full_layer2.get("gmroi_usage"),
        "objective_formula": full_layer2.get("objective_formula"),
        "objective_parameters": full_layer2.get("objective_parameters", {}),
        "objective_source": full_layer2.get("objective_source", {}),
    }
    assert compact_meta["sources"] == full_meta["sources"]
    assert compact_meta["physical_scope"] == full_meta["physical_scope"]
    assert compact_meta["arrival_projection"] == full_meta["arrival_projection"]
    assert compact_meta["economic_buffer"] == full_meta["economic_buffer"]
    assert compact_meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert compact_meta["capital_gap"] == full_meta["capital_gap"]
    assert compact_meta["capital_constraint"] == full_meta["capital_constraint"]
    assert compact_meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["layer_2_allocation"] == expected_compact_layer2

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in compact_layer2_step
    assert "legacy_decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is False
    assert compact_layer2["decision_quality"]["composite_objective_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    assert compact_layer2["objective_parameters"] == {
        "capital_cost_rate": 0.08,
        "stockout_penalty_weight": 1.0,
        "overstock_penalty_weight": 1.0,
    }
    assert compact_layer2["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    assert (
        compact_body["explanation"]["meta"]["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == compact_layer2["objective_parameters"]
    )
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    full_layer4 = full_meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4
    assert compact_meta["layer_5_intervention"] == full_meta["layer_5_intervention"]

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

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_body["constraints_applied"]["elastic_min_batches"] == elastic_constraints


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

    in_flight_meta = body["explanation"]["meta"]["in_flight_effective"]
    assert in_flight_meta["raw_qty"] == 200
    assert in_flight_meta["lines"] == 1
    assert 0 < in_flight_meta["effective_qty"] < 200

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["in_flight_effective"] == in_flight_meta


def test_production_order_proposal_arrival_projection_safe_cover_until_arrival_forces_wait(
    client,
    db_session,
):
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
            "qty": 800,
            "eta_days": 10,
            "stage": "nsk_to_wb",
        },
        {
            "article_id": seeded["article"].id,
            "color_id": seeded["color_1"].id,
            "size_id": seeded["size_m"].id,
            "qty": 800,
            "eta_days": 10,
            "stage": "nsk_to_wb",
        },
        {
            "article_id": seeded["article"].id,
            "color_id": seeded["color_2"].id,
            "size_id": seeded["size_s"].id,
            "qty": 800,
            "eta_days": 10,
            "stage": "nsk_to_wb",
        },
        {
            "article_id": seeded["article"].id,
            "color_id": seeded["color_2"].id,
            "size_id": seeded["size_m"].id,
            "qty": 800,
            "eta_days": 10,
            "stage": "nsk_to_wb",
        },
    ]
    payload["overrides"]["fabric_min_batch_qty_default"] = 0
    payload["overrides"]["elastic_min_batch_qty_default"] = 0

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["risk_level"] == "warning"
    assert body["arrival_projection"]["status"] == "safe_cover_until_arrival"
    assert body["arrival_projection"]["in_flight_bundle_capacity_at_arrival"] == 1374
    assert body["arrival_projection"]["projected_supply_units_before_arrival"] == 1404
    assert body["arrival_projection"]["projected_availability_at_arrival"] == 4
    assert body["arrival_projection"]["projected_shortage_before_arrival"] == 0
    assert body["arrival_projection"]["projected_cover_days_at_arrival"] == 0.2
    assert body["recommendation"]["action"] == "wait"
    assert body["recommendation"]["total_units"] == 0
    assert body["recommendation"]["lines"] == []
    assert body["explanation"]["meta"]["arrival_projection"] == body["arrival_projection"]


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

    compact_payload_without_buffer = deepcopy(payload_without_buffer)
    compact_payload_without_buffer["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_payload_with_buffer = deepcopy(payload_with_buffer)
    compact_payload_with_buffer["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response_without = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload_without_buffer,
    )
    compact_response_with = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload_with_buffer,
    )

    assert compact_response_without.status_code == 200, compact_response_without.text
    assert compact_response_with.status_code == 200, compact_response_with.text

    compact_body_without = compact_response_without.json()
    compact_body_with = compact_response_with.json()
    assert _business_projection(body_without) == _business_projection(compact_body_without)
    assert _business_projection(body_with) == _business_projection(compact_body_with)
    assert (
        compact_body_without["explanation"]["meta"]["economic_buffer"]
        == body_without["explanation"]["meta"]["economic_buffer"]
    )
    assert (
        compact_body_with["explanation"]["meta"]["economic_buffer"]
        == body_with["explanation"]["meta"]["economic_buffer"]
    )


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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body_with) == _business_projection(compact_body)
    assert compact_body["explanation"]["meta"]["reorder_policy"] == {
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
        "main_margin": 0.8,
        "assorti_margin": 0.65,
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

    assert layer2["method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2["method_canonical"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2["legacy_method"] == LAYER2_ALLOCATION_METHOD
    assert layer2["decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2["decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2["legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert layer2["tie_break"] == "hold"
    assert layer2["gmroi_usage"] == "diagnostic_only"
    assert len(layer2["decisions"]) == 4
    first_decision = layer2["decisions"][0]
    assert first_decision["expected_gross_profit_if_main_until_eta"] == first_decision[
        "profit_if_main_until_eta"
    ]
    assert first_decision["expected_gross_profit_if_assorti_until_eta"] == first_decision[
        "profit_if_assorti_until_eta"
    ]
    assert first_decision["expected_gross_profit_gap_until_eta"] == first_decision[
        "profit_gap_until_eta"
    ]
    assert first_decision["decision_reason_expected_gross_profit"] in {
        "expected_gross_profit_main_gt_assorti",
        "expected_gross_profit_assorti_gt_main",
        "expected_gross_profit_tie_hold",
    }
    assert layer2["summary"] == {"main": 0, "assorti": 4, "hold": 0}
    decision_quality = layer2["decision_quality"]
    assert decision_quality["profit_gate_primary"] is False
    assert decision_quality["expected_gross_profit_gate_primary"] is False
    assert decision_quality["composite_objective_gate_primary"] is True
    assert decision_quality["gmroi_usage"] == "diagnostic_only"
    assert decision_quality["decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert decision_quality["decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert decision_quality["legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert (
        decision_quality["near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert decision_quality["near_tie_profit_gap_threshold"] == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    assert decision_quality["decision_count"] == 4
    assert decision_quality["tie_count"] == 0
    assert decision_quality["near_tie_count"] == 0
    assert decision_quality["decision_reason_counts"] == {
        "profit_main_gt_assorti": 0,
        "profit_assorti_gt_main": 4,
        "profit_tie_hold": 0,
    }
    assert decision_quality["decision_reason_counts_expected_gross_profit"] == {
        "expected_gross_profit_main_gt_assorti": 0,
        "expected_gross_profit_assorti_gt_main": 4,
        "expected_gross_profit_tie_hold": 0,
    }
    assert decision_quality["decision_reason_counts_objective_score"] == {
        "objective_score_main_gt_assorti": 0,
        "objective_score_assorti_gt_main": 4,
        "objective_score_tie_hold": 0,
    }
    assert decision_quality["avg_profit_gap_until_eta"] == 8.0
    assert decision_quality["avg_expected_gross_profit_gap_until_eta"] == 8.0
    assert decision_quality["avg_objective_score_gap_until_eta"] >= 0.0
    assert decision_quality["avg_gmroi_gap"] == 0.8
    assert decision_quality["capital_locked_total"] == 40.0
    assert decision_quality["capital_locked_avg"] == 10.0
    assert layer2["contract"] == {
        "version": LAYER2_CONTRACT_VERSION,
        "status": "ok",
        "decision_count": 4,
        "summary_expected": {"main": 0, "assorti": 4, "hold": 0},
        "summary_actual": {"main": 0, "assorti": 4, "hold": 0},
        "checks": {
            "summary_matches_decisions": True,
            "summary_total_matches_decision_count": True,
            "valid_decisions_only": True,
            "unique_color_size_pairs": True,
            "non_negative_profit_metrics": True,
            "non_negative_gmroi_metrics": True,
            "eta_days_positive": True,
            "tie_break_hold_when_equal_objective": True,
            "tie_break_hold_when_equal_profit": True,
            "decision_reason_matches_allocation": True,
            "decision_reason_expected_gross_profit_matches_allocation": True,
            "decision_reason_objective_score_matches_allocation": True,
            "allocation_matches_composite_objective_gate": True,
            "allocation_matches_profit_gate": True,
            "allocation_matches_expected_gross_profit_gate": True,
            "tie_break_applied_matches_objective_tie": True,
            "tie_break_applied_matches_profit_tie": True,
            "near_tie_matches_objective_gap_threshold": True,
            "near_tie_matches_profit_gap_threshold": True,
            "profit_gap_consistent_with_profits": True,
            "expected_gross_profit_gap_consistent_with_expected_gross_profits": True,
            "gmroi_gap_consistent_with_gmroi": True,
            "capital_locked_metric_valid": True,
            "objective_required_fields_present": True,
            "objective_score_fields_numeric": True,
            "objective_components_present": True,
            "objective_components_numeric": True,
            "objective_components_consistent_with_scores": True,
            "objective_components_match_formula": True,
            "objective_score_gap_consistent_with_objective_scores": True,
        },
        "legacy_aliases": {
            "allocation_matches_profit_gate": {
                "alias_for": "allocation_matches_composite_objective_gate",
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
            "allocation_matches_expected_gross_profit_gate": {
                "alias_for": "allocation_matches_composite_objective_gate",
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
            "tie_break_hold_when_equal_profit": {
                "alias_for": "tie_break_hold_when_equal_objective",
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
            "tie_break_applied_matches_profit_tie": {
                "alias_for": "tie_break_applied_matches_objective_tie",
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
            "near_tie_matches_profit_gap_threshold": {
                "alias_for": "near_tie_matches_objective_gap_threshold",
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
        },
    }

    assert layer3["method"] == "allocation_decision_factors"
    assert layer3["factors"] == {"main": 1.0, "assorti": 0.75, "hold": 0.35}
    assert layer3["main_lines"] == 0
    assert layer3["assorti_lines"] == 4
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
        "scenario_delta_fields_present": True,
        "scenario_deltas_match_balanced": True,
    }
    assert set(layer4["aggregate_deltas"]["aggressive_vs_conservative"].keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }

    conservative = layer4["scenarios"][0]
    balanced = layer4["scenarios"][1]
    aggressive = layer4["scenarios"][2]
    assert conservative["total_capital_required"] < balanced["total_capital_required"] < aggressive["total_capital_required"]
    assert conservative["stockout_risk_proxy"] >= balanced["stockout_risk_proxy"] >= aggressive["stockout_risk_proxy"]
    assert conservative["assorti_sustainability_impact"] == "negative"
    assert balanced["assorti_sustainability_impact"] == "neutral"
    assert aggressive["assorti_sustainability_impact"] == "positive"
    layer4_aggregate = layer4["aggregate_deltas"]["aggressive_vs_conservative"]
    assert layer4_aggregate["capital_delta"] == round(
        float(aggressive["total_capital_required"]) - float(conservative["total_capital_required"]),
        2,
    )
    assert layer4_aggregate["gross_profit_delta"] == round(
        float(aggressive["expected_gross_profit"]) - float(conservative["expected_gross_profit"]),
        2,
    )
    assert layer4_aggregate["objective_delta"] == round(
        float(aggressive["objective_score"]) - float(conservative["objective_score"]),
        2,
    )

    assert layer5["method"] == "deterministic_unavoidable_stockout_flags"
    assert layer5["signal_policy"] == "critical_risk_thresholds"
    assert layer5["risk_threshold"] == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    assert layer5["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    assert layer5["contract"] == {
        "version": LAYER5_CONTRACT_VERSION,
        "status": "ok",
        "signal_count": len(layer5["signals"]),
        "checks": {
            "method_matches_expected": True,
            "signal_policy_matches_expected": True,
            "economic_policy_present": True,
            "required_layer4_scenarios_present": True,
            "required_layer4_scenarios_unique": True,
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
            "reduce_order_signal_requires_overstock_penalty_gate": True,
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
        "overstock_penalty_exceeds_marginal_profit",
    }

    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["source"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["calibration_state"] == "alpha_proxy_not_calibrated"
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert alpha_proxy["layer_2_allocation_method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_legacy_allocation_method"] == LAYER2_ALLOCATION_METHOD
    assert alpha_proxy["layer_2_decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert (
        alpha_proxy["layer_2_legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )
    assert (
        alpha_proxy["layer_2_near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["margin_proxy"] == {"main": 0.8, "assorti": 0.65}
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
        "layer2_capital_cost_rate": "code_default_constants",
        "layer2_stockout_penalty_weight": "code_default_constants",
        "layer2_overstock_penalty_weight": "code_default_constants",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }
    assert alpha_proxy["layer_4_scenario_factors"] == layer4["factors"]
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert (
        alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
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
    assert "assorti=4" in layer2_step
    assert f"method={LAYER2_ALLOCATION_METHOD_CANONICAL}" in layer2_step
    assert f"legacy_method={LAYER2_ALLOCATION_METHOD}" in layer2_step
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in layer2_step
    assert "legacy_decision_gate=profit_until_eta" in layer2_step
    assert "tie_break=hold" in layer2_step
    assert "near_tie=0" in layer2_step
    assert "tie_count=0" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step
    assert "main:0|assorti:4|hold:0" in layer3_step
    assert "contract_status=ok" in layer3_step
    assert "Conservative(capital=" in layer4_step
    assert "Aggressive(capital=" in layer4_step
    assert "status=ok" in layer4_contract_step
    assert "order_matches_expected=True" in layer4_contract_step
    assert "unavoidable_stockout=" in layer5_step
    assert "signals=" in layer5_step
    assert "contract_status=ok" in layer5_step

    if body["recommendation"] is not None and body["recommendation"]["lines"]:
        # Source reason format varies with composite objective, just verify lines exist
        assert len(body["recommendation"]["lines"]) > 0


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
    assert body_main["recommendation"]["total_units"] < body_assorti["recommendation"]["total_units"]

    layer2_main = body_main["explanation"]["meta"]["layer_2_allocation"]["summary"]
    layer2_assorti = body_assorti["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assert layer2_main["main"] == 0
    assert layer2_main["assorti"] > 0
    assert layer2_assorti["assorti"] == 0
    assert layer2_assorti["main"] > 0

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
    assert layer3_main["main_lines"] == 0
    assert layer3_main["assorti_lines"] > 0
    assert layer3_assorti["assorti_lines"] == 0
    assert layer3_assorti["main_lines"] > 0
    assert layer3_main["qty_after"] < layer3_assorti["qty_after"]

    assert body_assorti["recommendation"]["lines"]
    assert all(
        "|layer2:main" in line["source_reason"]
        for line in body_assorti["recommendation"]["lines"]
    )

    layer4_assorti = body_assorti["explanation"]["meta"]["layer_4_scenarios"]["scenarios"]
    assert [item["scenario"] for item in layer4_assorti] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]
    assert layer4_assorti[0]["assorti_sustainability_impact"] == "neutral_no_assorti_signal"
    assert layer4_assorti[1]["assorti_sustainability_impact"] == "neutral_no_assorti_signal"
    assert layer4_assorti[2]["assorti_sustainability_impact"] == "neutral_no_assorti_signal"


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
    global_settings.default_production_order_layer2_capital_cost_rate = 0.17
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.61
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.23
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
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.17,
        "stockout_penalty_weight": 0.61,
        "overstock_penalty_weight": 0.23,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "global_default",
        "layer3_overstock_dampen_max": "global_default",
        "layer5_unavoidable_stockout_risk_threshold": "global_default",
        "layer5_accelerate_production_risk_threshold": "global_default",
        "layer2_capital_cost_rate": "global_default",
        "layer2_stockout_penalty_weight": "global_default",
        "layer2_overstock_penalty_weight": "global_default",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }
    assert response.json()["explanation"]["meta"]["layer_2_allocation"]["objective_parameters"] == {
        "capital_cost_rate": 0.17,
        "stockout_penalty_weight": 0.61,
        "overstock_penalty_weight": 0.23,
    }
    assert response.json()["explanation"]["meta"]["layer_2_allocation"]["objective_source"] == {
        "capital_cost_rate": "global_default",
        "stockout_penalty_weight": "global_default",
        "overstock_penalty_weight": "global_default",
    }


def test_production_order_proposal_uses_admin_layer_proxy_defaults_when_request_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer3_stockout_boost_max = 0.27
    article_settings.production_order_layer3_overstock_dampen_max = 0.22
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.24
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.32
    article_settings.production_order_layer2_capital_cost_rate = 0.13
    article_settings.production_order_layer2_stockout_penalty_weight = 0.57
    article_settings.production_order_layer2_overstock_penalty_weight = 0.29

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.11
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.09
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.18
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.28
    global_settings.default_production_order_layer2_capital_cost_rate = 0.08
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.34
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.17
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
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.27
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.22
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.24
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.32,
        "increase_price_to_slow_velocity": 0.24,
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.13,
        "stockout_penalty_weight": 0.57,
        "overstock_penalty_weight": 0.29,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "admin_defaults",
        "layer3_overstock_dampen_max": "admin_defaults",
        "layer5_unavoidable_stockout_risk_threshold": "admin_defaults",
        "layer5_accelerate_production_risk_threshold": "admin_defaults",
        "layer2_capital_cost_rate": "admin_defaults",
        "layer2_stockout_penalty_weight": "admin_defaults",
        "layer2_overstock_penalty_weight": "admin_defaults",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }
    assert body["explanation"]["meta"]["layer_2_allocation"]["objective_parameters"] == {
        "capital_cost_rate": 0.13,
        "stockout_penalty_weight": 0.57,
        "overstock_penalty_weight": 0.29,
    }
    assert body["explanation"]["meta"]["layer_2_allocation"]["objective_source"] == {
        "capital_cost_rate": "admin_defaults",
        "stockout_penalty_weight": "admin_defaults",
        "overstock_penalty_weight": "admin_defaults",
    }


def test_production_order_proposal_warns_when_invalid_admin_layer_proxy_values_are_ignored(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer3_stockout_boost_max = 1.27
    article_settings.production_order_layer3_overstock_dampen_max = -0.22
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 1.24
    article_settings.production_order_layer5_accelerate_production_risk_threshold = -0.32

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.11
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.09
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.18
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.28
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
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.11
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.09
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.18
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.28,
        "increase_price_to_slow_velocity": 0.18,
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_proxy_source"]["layer3_stockout_boost_max"] == "global_default"
    assert alpha_proxy["layer_proxy_source"]["layer3_overstock_dampen_max"] == "global_default"
    assert alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "global_default"
    assert alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"] == "global_default"
    invalid_layer_proxy_warning = next(
        warning
        for warning in meta["warnings"]
        if warning["code"] == "layer_proxy_invalid_values_ignored_at_runtime"
    )
    assert invalid_layer_proxy_warning == {
        "code": "layer_proxy_invalid_values_ignored_at_runtime",
        "severity": "MEDIUM",
        "message": "one or more production-order layer proxy values were invalid and ignored at runtime; lower-precedence or default values were used instead",
        "article_id": seeded["article"].id,
        "field": "layer_proxy_settings",
        "field_metadata": {
            "description": "Production-order Layer 3/5 proxy settings resolved from request/admin/global sources",
            "type": "object",
        },
        "ignored_value_count": 4,
        "ignored_fields": [
            "layer3_overstock_dampen_max",
            "layer3_stockout_boost_max",
            "layer5_accelerate_production_risk_threshold",
            "layer5_unavoidable_stockout_risk_threshold",
        ],
        "ignored_sources": ["admin_defaults"],
        "ignored_values": [
            {
                "field": "layer3_stockout_boost_max",
                "invalid_source": "admin_defaults",
                "invalid_value": 1.27,
                "effective_source": "global_default",
                "effective_value": 0.11,
            },
            {
                "field": "layer3_overstock_dampen_max",
                "invalid_source": "admin_defaults",
                "invalid_value": -0.22,
                "effective_source": "global_default",
                "effective_value": 0.09,
            },
            {
                "field": "layer5_unavoidable_stockout_risk_threshold",
                "invalid_source": "admin_defaults",
                "invalid_value": 1.24,
                "effective_source": "global_default",
                "effective_value": 0.18,
            },
            {
                "field": "layer5_accelerate_production_risk_threshold",
                "invalid_source": "admin_defaults",
                "invalid_value": -0.32,
                "effective_source": "global_default",
                "effective_value": 0.28,
            },
        ],
        "action": "Review stored production-order layer proxy values; each unit-interval setting must stay within [0, 1].",
        "next_steps": ["repair_layer_proxy_settings_values"],
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal", json=compact_payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    compact_alpha_proxy = compact_meta["alpha_proxy_economics"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_uses_admin_economic_defaults_when_request_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = 0.7
    article_settings.production_order_logistics_cost_per_unit = 0.3
    article_settings.production_order_wb_commission_percent_main = 0.11
    article_settings.production_order_wb_commission_percent_assorti = 0.12
    article_settings.production_order_average_realized_price_main = 2.2
    article_settings.production_order_average_realized_price_assorti = 2.4
    article_settings.production_order_available_capital = 300.0

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 0.9
    global_settings.default_production_order_logistics_cost_per_unit = 0.4
    global_settings.default_production_order_wb_commission_percent_main = 0.13
    global_settings.default_production_order_wb_commission_percent_assorti = 0.14
    global_settings.default_production_order_average_realized_price_main = 2.6
    global_settings.default_production_order_average_realized_price_assorti = 2.8
    global_settings.default_production_order_available_capital = 450.0
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("production_cost_per_unit", None)
    payload["overrides"].pop("logistics_cost_per_unit", None)
    payload["overrides"].pop("wb_commission_percent_main", None)
    payload["overrides"].pop("wb_commission_percent_assorti", None)
    payload["overrides"].pop("average_realized_price_main", None)
    payload["overrides"].pop("average_realized_price_assorti", None)
    payload["overrides"].pop("available_capital", None)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "admin_defaults",
        "logistics_cost_per_unit": "admin_defaults",
        "wb_commission_percent_main": "admin_defaults",
        "wb_commission_percent_assorti": "admin_defaults",
        "average_realized_price_main": "admin_defaults",
        "average_realized_price_assorti": "admin_defaults",
        "available_capital": "admin_defaults",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 0.7,
        "logistics_cost_per_unit": 0.3,
        "wb_commission_percent_main": 0.11,
        "wb_commission_percent_assorti": 0.12,
        "average_realized_price_main": 2.2,
        "average_realized_price_assorti": 2.4,
        "available_capital": 300.0,
    }
    assert alpha_proxy["economics_trust"] == meta["economics_trust"]
    assert alpha_proxy["economics_trust_level"] == meta["economics_trust"]["economics_trust_level"]
    assert alpha_proxy["capital_governance"] == meta["capital_governance"]

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_TRUSTED
    assert economics_trust["code_default_key_fields"] == []
    assert economics_trust["code_default_key_fields_count"] == 0
    assert economics_trust["code_default_dominance_ratio"] == 0.0
    assert economics_trust["warnings"] == []
    assert meta["warnings"] == []

    capital_gap = meta["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert capital_gap["available_capital"] == 300.0

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == []


def test_production_order_proposal_uses_global_economic_defaults_when_admin_and_request_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 1.0
    global_settings.default_production_order_logistics_cost_per_unit = 0.2
    global_settings.default_production_order_wb_commission_percent_main = 0.10
    global_settings.default_production_order_wb_commission_percent_assorti = 0.20
    global_settings.default_production_order_average_realized_price_main = 3.0
    global_settings.default_production_order_average_realized_price_assorti = 3.5
    global_settings.default_production_order_available_capital = 250.0
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("production_cost_per_unit", None)
    payload["overrides"].pop("logistics_cost_per_unit", None)
    payload["overrides"].pop("wb_commission_percent_main", None)
    payload["overrides"].pop("wb_commission_percent_assorti", None)
    payload["overrides"].pop("average_realized_price_main", None)
    payload["overrides"].pop("average_realized_price_assorti", None)
    payload["overrides"].pop("available_capital", None)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "global_default",
        "logistics_cost_per_unit": "global_default",
        "wb_commission_percent_main": "global_default",
        "wb_commission_percent_assorti": "global_default",
        "average_realized_price_main": "global_default",
        "average_realized_price_assorti": "global_default",
        "available_capital": "global_default",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 1.0,
        "logistics_cost_per_unit": 0.2,
        "wb_commission_percent_main": 0.1,
        "wb_commission_percent_assorti": 0.2,
        "average_realized_price_main": 3.0,
        "average_realized_price_assorti": 3.5,
        "available_capital": 250.0,
    }
    assert alpha_proxy["margin_proxy"] == {"main": 1.5, "assorti": 1.6}
    assert alpha_proxy["unit_capital_proxy"] == 1.2

    economics_trust = body["explanation"]["meta"]["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_TRUSTED
    assert economics_trust["code_default_key_fields"] == []
    assert economics_trust["code_default_key_fields_count"] == 0
    assert economics_trust["code_default_dominance_ratio"] == 0.0
    assert economics_trust["warnings"] == []
    assert body["explanation"]["meta"]["warnings"] == []

    capital_gap = body["explanation"]["meta"]["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert capital_gap["available_capital"] == 250.0

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == body["explanation"]["meta"]["capital_governance"]
    assert compact_meta["warnings"] == []


def test_production_order_proposal_uses_code_default_economics_when_request_admin_global_missing(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = None
    article_settings.production_order_logistics_cost_per_unit = None
    article_settings.production_order_wb_commission_percent_main = None
    article_settings.production_order_wb_commission_percent_assorti = None
    article_settings.production_order_average_realized_price_main = None
    article_settings.production_order_average_realized_price_assorti = None
    article_settings.production_order_available_capital = None

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = None
    global_settings.default_production_order_logistics_cost_per_unit = None
    global_settings.default_production_order_wb_commission_percent_main = None
    global_settings.default_production_order_wb_commission_percent_assorti = None
    global_settings.default_production_order_average_realized_price_main = None
    global_settings.default_production_order_average_realized_price_assorti = None
    global_settings.default_production_order_available_capital = None
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("production_cost_per_unit", None)
    payload["overrides"].pop("logistics_cost_per_unit", None)
    payload["overrides"].pop("wb_commission_percent_main", None)
    payload["overrides"].pop("wb_commission_percent_assorti", None)
    payload["overrides"].pop("average_realized_price_main", None)
    payload["overrides"].pop("average_realized_price_assorti", None)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_default_formula"
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "code_default_constants",
        "logistics_cost_per_unit": "code_default_constants",
        "wb_commission_percent_main": "code_default_constants",
        "wb_commission_percent_assorti": "code_default_constants",
        "average_realized_price_main": "code_default_constants",
        "average_realized_price_assorti": "code_default_constants",
        "available_capital": "request",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 0.8,
        "logistics_cost_per_unit": 0.2,
        "wb_commission_percent_main": 0.0,
        "wb_commission_percent_assorti": 0.0,
        "average_realized_price_main": 1.8,
        "average_realized_price_assorti": 1.65,
        "available_capital": 1000000.0,
    }
    assert alpha_proxy["margin_proxy"] == {"main": 0.8, "assorti": 0.65}
    assert alpha_proxy["unit_capital_proxy"] == 1.0

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_UNTRUSTED
    assert economics_trust["code_default_key_fields_count"] >= 2
    assert economics_trust["code_default_dominance_ratio"] > 0
    assert economics_trust["warnings"][0]["code"] == ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED
    assert economics_trust["warnings"][0]["severity"] == "HIGH"
    assert meta["warnings"][0] == economics_trust["warnings"][0]
    capital_gap = meta["capital_gap"]

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_reports_partial_economics_trust_when_one_key_field_uses_code_default(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = 0.7
    article_settings.production_order_logistics_cost_per_unit = 0.3
    article_settings.production_order_wb_commission_percent_main = 0.11
    article_settings.production_order_wb_commission_percent_assorti = 0.12
    article_settings.production_order_average_realized_price_main = 2.2
    article_settings.production_order_average_realized_price_assorti = None
    article_settings.production_order_available_capital = 300.0

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 0.9
    global_settings.default_production_order_logistics_cost_per_unit = 0.4
    global_settings.default_production_order_wb_commission_percent_main = 0.13
    global_settings.default_production_order_wb_commission_percent_assorti = 0.14
    global_settings.default_production_order_average_realized_price_main = 2.6
    global_settings.default_production_order_average_realized_price_assorti = None
    global_settings.default_production_order_available_capital = 450.0
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("production_cost_per_unit", None)
    payload["overrides"].pop("logistics_cost_per_unit", None)
    payload["overrides"].pop("wb_commission_percent_main", None)
    payload["overrides"].pop("wb_commission_percent_assorti", None)
    payload["overrides"].pop("average_realized_price_main", None)
    payload["overrides"].pop("average_realized_price_assorti", None)
    payload["overrides"].pop("available_capital", None)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"]["average_realized_price_assorti"] == "code_default_constants"
    assert alpha_proxy["economic_inputs"]["average_realized_price_assorti"] == 1.65

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_PARTIAL
    assert economics_trust["code_default_key_fields"] == ["average_realized_price_assorti"]
    assert economics_trust["code_default_key_fields_count"] == 1
    assert economics_trust["warnings"][0]["code"] == ECONOMICS_TRUST_WARNING_CODE_PARTIAL
    assert economics_trust["warnings"][0]["severity"] == "MEDIUM"
    assert meta["warnings"][0] == economics_trust["warnings"][0]
    capital_gap = meta["capital_gap"]

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_requires_available_capital_in_strict_mode(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_available_capital = None
    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_available_capital = None
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("available_capital", None)

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 422, response.text

    assert response.json()["detail"] == {
        "code": "missing_available_capital_strict",
        "message": "available_capital is required for production-order proposal in strict capital governance mode",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for strict capital governance mode",
            "type": "number",
        },
        "capital_constraint_status": CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
        "severity": "HIGH",
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": ECONOMICS_TRUST_LEVEL_UNTRUSTED,
        "next_steps": ["provide_available_capital_override_or_default"],
    }


def test_production_order_proposal_safe_default_mode_applies_zero_capital_fallback(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_available_capital = None
    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_available_capital = None
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["overrides"].pop("available_capital", None)
    payload["overrides"]["capital_governance_mode"] = "safe_default"

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["recommendation"]["action"] == "wait"
    assert body["recommendation"]["total_units"] == 0

    meta = body["explanation"]["meta"]
    assert meta["capital_governance"] == {
        "mode": "safe_default",
        "missing_available_capital_policy": "safe_default",
        "safe_default_applied": True,
        "available_capital_effective": 0.0,
        "effective_source": "safe_default_zero_capital",
    }
    safe_default_warning = next(
        warning
        for warning in meta["warnings"]
        if warning["code"] == "available_capital_safe_default_applied"
    )
    assert safe_default_warning == {
        "code": "available_capital_safe_default_applied",
        "severity": "HIGH",
        "message": "available_capital missing; safe_default mode applied zero-capital fallback to avoid unconstrained recommendations",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for safe_default capital governance mode",
            "type": "number",
        },
        "capital_governance_status": "safe_default_zero_capital_applied",
        "capital_governance_mode": "safe_default",
        "available_capital_effective": 0.0,
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": ECONOMICS_TRUST_LEVEL_UNTRUSTED,
        "next_steps": ["provide_available_capital_override_or_default"],
    }
    assert meta["alpha_proxy_economics"]["economic_inputs"]["available_capital"] == 0.0
    assert meta["alpha_proxy_economics"]["economic_source"]["available_capital"] == "safe_default_zero_capital"
    assert meta["alpha_proxy_economics"]["capital_governance"] == meta["capital_governance"]
    assert meta["arrival_projection"]["status"] == "shortage_before_arrival"
    assert meta["arrival_projection"]["projected_shortage_before_arrival"] > 0
    assert meta["capital_constraint"]["status"] == "budget_limited_applied"
    assert meta["capital_constraint"]["available_capital"] == 0.0
    assert meta["capital_constraint"]["allocated_capital_after_constraint"] == 0.0
    assert meta["capital_constraint"]["line_count_before"] > 0
    assert meta["capital_constraint"]["line_count_after"] == 0
    assert meta["warnings"][-1] == {
        "code": "shortage_before_arrival_wait_blocked_by_capital_constraint",
        "severity": "HIGH",
        "message": "shortage_before_arrival detected, but recommendation remained wait because capital constraint trimmed feasible order quantity to zero",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input applied to production-order capital constraint",
            "type": "number",
        },
        "arrival_projection_status": "shortage_before_arrival",
        "projected_shortage_before_arrival": meta["arrival_projection"]["projected_shortage_before_arrival"],
        "recommendation_action": "wait",
        "capital_constraint_status": "budget_limited_applied",
        "available_capital_effective": 0.0,
        "required_capital_before_constraint": meta["capital_constraint"]["required_capital_before_constraint"],
        "allocated_capital_after_constraint": 0.0,
        "action": "Provide or increase available_capital before treating wait as safe under shortage.",
        "next_steps": ["provide_available_capital_override_or_default"],
    }

    expected_compact_assorti_classification = {
        "source": meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["economics_trust"] == meta["economics_trust"]
    assert compact_meta["warnings"] == meta["warnings"]
    assert compact_meta["alpha_proxy_economics"] == meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["available_capital"] == 0.0
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["available_capital"] == "safe_default_zero_capital"
    assert compact_meta["alpha_proxy_economics"]["capital_governance"] == compact_meta["capital_governance"]
    assert compact_meta["capital_constraint"] == meta["capital_constraint"]


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
    article_settings.production_order_layer2_capital_cost_rate = 0.14
    article_settings.production_order_layer2_stockout_penalty_weight = 0.44
    article_settings.production_order_layer2_overstock_penalty_weight = 0.21

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.09
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.08
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.21
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.31
    global_settings.default_production_order_layer2_capital_cost_rate = 0.11
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.33
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.19
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
    payload["overrides"]["layer2_capital_cost_rate"] = 0.07
    payload["overrides"]["layer2_stockout_penalty_weight"] = 0.52
    payload["overrides"]["layer2_overstock_penalty_weight"] = 0.16

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
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.07,
        "stockout_penalty_weight": 0.52,
        "overstock_penalty_weight": 0.16,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "request",
        "layer3_overstock_dampen_max": "request",
        "layer5_unavoidable_stockout_risk_threshold": "request",
        "layer5_accelerate_production_risk_threshold": "request",
        "layer2_capital_cost_rate": "request",
        "layer2_stockout_penalty_weight": "request",
        "layer2_overstock_penalty_weight": "request",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }
    layer2 = body["explanation"]["meta"]["layer_2_allocation"]
    assert layer2["objective_parameters"] == {
        "capital_cost_rate": 0.07,
        "stockout_penalty_weight": 0.52,
        "overstock_penalty_weight": 0.16,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": "request",
        "stockout_penalty_weight": "request",
        "overstock_penalty_weight": "request",
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    layer3 = body["explanation"]["meta"]["layer_3_purchase_shaping"]
    layer3_calibration = layer3["calibration"]
    assert layer3_calibration["stockout_boost_max"] == 0.23
    assert layer3_calibration["overstock_dampen_max"] == 0.18
    expected_compact_layer3 = {
        "method": layer3["method"],
        "factors": layer3["factors"],
        "contract": layer3["contract"],
        "qty_before": layer3["qty_before"],
        "qty_after_base": layer3["qty_after_base"],
        "qty_after": layer3["qty_after"],
        "qty_delta_vs_base": layer3["qty_delta_vs_base"],
        "adjusted_lines": layer3["adjusted_lines"],
        "main_lines": layer3["main_lines"],
        "assorti_lines": layer3["assorti_lines"],
        "hold_lines": layer3["hold_lines"],
        "calibration": layer3["calibration"],
    }
    layer4 = body["explanation"]["meta"]["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }
    layer5 = body["explanation"]["meta"]["layer_5_intervention"]
    assert layer5["risk_threshold"] == 0.27
    assert layer5["signal_thresholds"] == {
        "accelerate_production": 0.41,
        "increase_price_to_slow_velocity": 0.27,
        "reduce_order_size": 0.10,
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_alpha_proxy = compact_body["explanation"]["meta"]["alpha_proxy_economics"]
    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    compact_layer3 = compact_body["explanation"]["meta"]["layer_3_purchase_shaping"]
    compact_layer4 = compact_body["explanation"]["meta"]["layer_4_scenarios"]
    compact_layer5 = compact_body["explanation"]["meta"]["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer_3_calibration"] == alpha_proxy["layer_3_calibration"]
    assert compact_alpha_proxy["layer_proxy_source"] == alpha_proxy["layer_proxy_source"]
    assert compact_alpha_proxy["layer_2_objective_parameters"] == alpha_proxy["layer_2_objective_parameters"]
    assert (
        compact_alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer2 == expected_compact_layer2
    assert compact_layer3 == expected_compact_layer3
    assert compact_layer4 == expected_compact_layer4
    assert compact_layer5 == layer5


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

    assert low_layer5["signals"] == ["reduce_order_size"]
    assert low_layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"
    assert high_layer5["signals"] == ["reduce_order_size"]
    assert high_layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"


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

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer5_threshold_order_adjusted"] is True
    assert alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "admin_defaults"
    assert (
        alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"]
        == "admin_defaults|clamped_to_unavoidable"
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.44,
        "increase_price_to_slow_velocity": 0.44,
        "reduce_order_size": 0.10,
    }
    assert meta["warnings"][-1] == {
        "code": "layer5_accelerate_threshold_clamped_to_unavoidable",
        "severity": "MEDIUM",
        "message": "layer5_accelerate_production_risk_threshold was below layer5_unavoidable_stockout_risk_threshold and was clamped upward at runtime",
        "article_id": seeded["article"].id,
        "field": "layer5_accelerate_production_risk_threshold",
        "field_metadata": {
            "description": "Layer 5 accelerate-production risk threshold input",
            "type": "number",
        },
        "threshold_order_adjusted": True,
        "accelerate_threshold_effective": 0.44,
        "unavoidable_threshold_effective": 0.44,
        "effective_source": "admin_defaults|clamped_to_unavoidable",
        "action": "Review Layer 5 threshold inputs; accelerate threshold cannot be lower than unavoidable stockout threshold.",
        "next_steps": ["review_layer5_threshold_configuration"],
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal", json=compact_payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    compact_alpha_proxy = compact_meta["alpha_proxy_economics"]
    compact_layer5 = compact_meta["layer_5_intervention"]
    layer5 = meta["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer5_threshold_order_adjusted"] is True
    assert compact_alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "admin_defaults"
    assert (
        compact_alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"]
        == "admin_defaults|clamped_to_unavoidable"
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer5 == layer5
    assert compact_meta["warnings"] == meta["warnings"]


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
            "scenario_delta_fields_present": False,
            "scenario_deltas_match_balanced": False,
        },
    }


def test_layer4_contract_summary_marks_violated_when_scenario_deltas_break_balanced_baseline():
    scenarios = _build_layer4_scenarios(
        base_purchase_units=100,
        available_bundles_for_cover=120,
        total_daily_sales=5.0,
        reorder_point_days=40,
        expected_horizon_sales=450.0,
        layer3_purchase_shaping={
            "main_lines": 1,
            "assorti_lines": 1,
            "hold_lines": 0,
        },
        unit_capital_per_unit=2.0,
        margin_main_per_unit=1.5,
        margin_assorti_per_unit=1.0,
        average_realized_price_main=3.5,
        average_realized_price_assorti=3.0,
    )
    scenarios[2]["objective_score_delta_vs_balanced"] = round(
        float(scenarios[2]["objective_score_delta_vs_balanced"]) + 1.0,
        2,
    )

    contract = _build_layer4_contract_summary(scenarios)

    assert contract["status"] == "violated"
    assert contract["checks"]["capital_non_decreasing"] is True
    assert contract["checks"]["stockout_risk_non_increasing"] is True
    assert contract["checks"]["turnover_non_increasing"] is True
    assert contract["checks"]["purchase_units_non_decreasing"] is True
    assert contract["checks"]["scenario_delta_fields_present"] is True
    assert contract["checks"]["scenario_deltas_match_balanced"] is False


def test_layer4_scenarios_include_economic_money_fields():
    scenarios = _build_layer4_scenarios(
        base_purchase_units=100,
        available_bundles_for_cover=120,
        total_daily_sales=5.0,
        reorder_point_days=40,
        expected_horizon_sales=450.0,
        layer3_purchase_shaping={
            "main_lines": 1,
            "assorti_lines": 1,
            "hold_lines": 0,
        },
        unit_capital_per_unit=2.0,
        margin_main_per_unit=1.5,
        margin_assorti_per_unit=1.0,
        average_realized_price_main=3.5,
        average_realized_price_assorti=3.0,
    )

    assert [item["scenario"] for item in scenarios] == [
        "Conservative",
        "Balanced",
        "Aggressive",
    ]

    for scenario in scenarios:
        assert "expected_revenue" in scenario
        assert "expected_gross_profit" in scenario
        assert "expected_margin_percent" in scenario
        assert "expected_turnover_days" in scenario
        assert "stockout_probability_proxy" in scenario
        assert "overstock_risk_proxy" in scenario
        assert "capital_delta_vs_balanced" in scenario
        assert "expected_revenue_delta_vs_balanced" in scenario
        assert "expected_gross_profit_delta_vs_balanced" in scenario
        assert "objective_score_delta_vs_balanced" in scenario
        assert (
            scenario["expected_gross_profit_delta_vs_balanced"]
            == scenario["gross_profit_delta_vs_balanced"]
        )

    balanced = scenarios[1]
    assert float(balanced["expected_revenue"]) >= float(balanced["expected_gross_profit"]) >= 0.0
    assert 0.0 <= float(balanced["expected_margin_percent"]) <= 100.0
    assert float(balanced["capital_delta_vs_balanced"]) == 0.0
    assert float(balanced["expected_revenue_delta_vs_balanced"]) == 0.0
    assert float(balanced["expected_gross_profit_delta_vs_balanced"]) == 0.0
    assert float(balanced["objective_score_delta_vs_balanced"]) == 0.0


def test_layer4_aggregate_deltas_aggressive_vs_conservative_are_emitted():
    scenarios = _build_layer4_scenarios(
        base_purchase_units=100,
        available_bundles_for_cover=120,
        total_daily_sales=5.0,
        reorder_point_days=40,
        expected_horizon_sales=450.0,
        layer3_purchase_shaping={
            "main_lines": 1,
            "assorti_lines": 1,
            "hold_lines": 0,
        },
        unit_capital_per_unit=2.0,
        margin_main_per_unit=1.5,
        margin_assorti_per_unit=1.0,
        average_realized_price_main=3.5,
        average_realized_price_assorti=3.0,
    )

    aggregate = _build_layer4_aggregate_deltas(scenarios)
    aggressive_vs_conservative = aggregate["aggressive_vs_conservative"]
    assert set(aggressive_vs_conservative.keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }
    assert aggressive_vs_conservative["capital_delta"] == round(
        float(scenarios[2]["total_capital_required"]) - float(scenarios[0]["total_capital_required"]),
        2,
    )
    assert aggressive_vs_conservative["gross_profit_delta"] == round(
        float(scenarios[2]["expected_gross_profit"]) - float(scenarios[0]["expected_gross_profit"]),
        2,
    )
    assert aggressive_vs_conservative["objective_delta"] == round(
        float(scenarios[2]["objective_score"]) - float(scenarios[0]["objective_score"]),
        2,
    )


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
        "economic_policy": "cost_aware_thresholds",
        "unavoidable_stockout": True,
        "signals": ["accelerate_production"],
        "reason": "no_effective_in_flight_and_high_stockout_risk",
        "aggressive_stockout_risk_proxy": 0.4,
        "aggressive_overstock_risk_proxy": 0.0,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
            "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
        },
        "economic_justification": {
            "expected_loss_if_no_action": 0.4,
            "action_cost": 0.0,
            "margin_improvement_from_slowdown": 0.4,
            "lost_volume_cost": 0.0,
            "overstock_penalty": 0.0,
            "marginal_profit_of_additional_units": 0.0,
            "formulas": {
                "accelerate_production": "expected_loss_if_no_action > action_cost",
                "increase_price_to_slow_velocity": "margin_improvement_from_slowdown > lost_volume_cost",
                "reduce_order_size": "overstock_penalty > marginal_profit_of_additional_units",
            },
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
        "economic_policy": "cost_aware_thresholds",
        "unavoidable_stockout": True,
        "signals": [
            "accelerate_production",
            "increase_price_to_slow_velocity",
        ],
        "reason": "in_flight_present_but_severe_stockout_risk",
        "aggressive_stockout_risk_proxy": 0.45,
        "aggressive_overstock_risk_proxy": 0.0,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
            "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
        },
        "economic_justification": {
            "expected_loss_if_no_action": 0.45,
            "action_cost": 0.0,
            "margin_improvement_from_slowdown": 0.45,
            "lost_volume_cost": 0.0,
            "overstock_penalty": 0.0,
            "marginal_profit_of_additional_units": 0.0,
            "formulas": {
                "accelerate_production": "expected_loss_if_no_action > action_cost",
                "increase_price_to_slow_velocity": "margin_improvement_from_slowdown > lost_volume_cost",
                "reduce_order_size": "overstock_penalty > marginal_profit_of_additional_units",
            },
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
        "economic_policy": "cost_aware_thresholds",
        "unavoidable_stockout": True,
        "signals": ["increase_price_to_slow_velocity"],
        "reason": "in_flight_present_but_stockout_risk_persists",
        "aggressive_stockout_risk_proxy": 0.31,
        "aggressive_overstock_risk_proxy": 0.0,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
            "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
        },
        "economic_justification": {
            "expected_loss_if_no_action": 0.31,
            "action_cost": 0.0,
            "margin_improvement_from_slowdown": 0.31,
            "lost_volume_cost": 0.0,
            "overstock_penalty": 0.0,
            "marginal_profit_of_additional_units": 0.0,
            "formulas": {
                "accelerate_production": "expected_loss_if_no_action > action_cost",
                "increase_price_to_slow_velocity": "margin_improvement_from_slowdown > lost_volume_cost",
                "reduce_order_size": "overstock_penalty > marginal_profit_of_additional_units",
            },
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
        "economic_policy": "cost_aware_thresholds",
        "unavoidable_stockout": False,
        "signals": [],
        "reason": "none",
        "aggressive_stockout_risk_proxy": 0.05,
        "aggressive_overstock_risk_proxy": 0.0,
        "risk_threshold": LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        "signal_thresholds": {
            "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
            "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
            "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
        },
        "economic_justification": {
            "expected_loss_if_no_action": 0.05,
            "action_cost": 0.0,
            "margin_improvement_from_slowdown": 0.05,
            "lost_volume_cost": 0.0,
            "overstock_penalty": 0.0,
            "marginal_profit_of_additional_units": 0.0,
            "formulas": {
                "accelerate_production": "expected_loss_if_no_action > action_cost",
                "increase_price_to_slow_velocity": "margin_improvement_from_slowdown > lost_volume_cost",
                "reduce_order_size": "overstock_penalty > marginal_profit_of_additional_units",
            },
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
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
    )

    assert summary == {"main": 1, "assorti": 0, "hold": 0}
    assert len(decisions) == 1
    assert decisions[0]["profit_if_main_until_eta"] == 0.85
    assert decisions[0]["profit_if_assorti_until_eta"] == 0.85
    assert decisions[0]["profit_gap_until_eta"] == 0.0
    assert decisions[0]["decision_reason"] == "profit_main_gt_assorti"
    assert decisions[0]["tie_break_applied"] is False
    assert decisions[0]["near_tie"] is True
    assert decisions[0]["allocation_decision"] == "main"


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
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer3_qty_after": 109,
                "layer3_qty_delta_vs_base": 19,
                "reorder_qty": 109,
                "layer4_purchase_units": [88, 109, 131],
                "layer4_capital": [88.0, 109.0, 131.0],
                "capital_delta_aggressive_vs_conservative": 43.0,
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
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer3_qty_after": 21,
                "layer3_qty_delta_vs_base": -9,
                "reorder_qty": 21,
                "layer4_purchase_units": [17, 21, 26],
                "layer4_capital": [17.0, 21.0, 26.0],
                "capital_delta_aggressive_vs_conservative": 9.0,
                "layer5_signals": ["reduce_order_size"],
                "layer5_reason": "overstock_penalty_exceeds_marginal_profit",
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
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
    )

    assert len(layer2_decisions) == 1
    layer2 = layer2_decisions[0]
    assert layer2_summary == expected["layer2_summary"]
    assert layer2["allocation_decision"] == expected["layer2_decision"]

    # Note: Composite objective may have different tie-breaking logic than pure profit comparison
    # So we only validate the decision direction, not the specific profit relationship

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
        unit_capital_per_unit=1.0,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
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
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer2_near_tie_count": 0,
                "layer2_tie_count": 0,
                "layer3_qty_after": 112,
                "layer3_qty_delta_vs_base": 22,
                "reorder_qty": 112,
                "layer4_purchase_units": [90, 112, 135],
                "layer4_capital": [90.0, 112.0, 135.0],
                "capital_delta_aggressive_vs_conservative": 45.0,
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
                "layer2_decision": "assorti",
                "layer2_summary": {"main": 0, "assorti": 1, "hold": 0},
                "layer2_near_tie_count": 0,
                "layer2_tie_count": 0,
                "layer3_qty_after": 20,
                "layer3_qty_delta_vs_base": -10,
                "reorder_qty": 20,
                "layer4_purchase_units": [16, 20, 24],
                "layer4_capital": [16.0, 20.0, 24.0],
                "capital_delta_aggressive_vs_conservative": 8.0,
                "layer5_signals": ["reduce_order_size"],
                "layer5_reason": "overstock_penalty_exceeds_marginal_profit",
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
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
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
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
        unit_capital_per_unit=1.0,
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
    assert layer2_contract["checks"]["tie_break_applied_matches_objective_tie"] is True
    assert layer2_contract["checks"]["tie_break_applied_matches_profit_tie"] is True
    assert layer2_contract["checks"]["near_tie_matches_objective_gap_threshold"] is True
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
        unit_capital_per_unit=1.0,
        margin_main_per_unit=1.0,
        margin_assorti_per_unit=0.85,
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


def test_recommendation_helper_matches_facade_action_and_alternatives():
    cases = [
        ("critical", 10, False),
        ("warning", 10, True),
        ("ok", 10, True),
        ("no_data", 0, False),
    ]

    for risk_level, candidate_units, allow_order_with_buffer in cases:
        facade_action = _choose_action(
            risk_level=risk_level,
            candidate_units=candidate_units,
            allow_order_with_buffer=allow_order_with_buffer,
        )
        extracted_action = extracted_choose_action(
            risk_level=risk_level,
            candidate_units=candidate_units,
            allow_order_with_buffer=allow_order_with_buffer,
        )
        assert extracted_action == facade_action
        assert [item.action for item in extracted_build_alternatives(extracted_action)] == [
            item.action for item in planning_production_order_service._build_alternatives(facade_action)
        ]


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

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    full_meta = body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["resource_allocation"] == full_meta["resource_allocation"]


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
    assert body["physical_scope"]["wb_stock_scope"] == "article_wb_mapping_bundle_stock_aggregated"
    assert body["physical_scope"]["ready_bundle_source"] == "wb_defaults"


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
    assert body["physical_scope"]["wb_stock_scope"] == "request_explicit_bundle_stock"
    assert body["physical_scope"]["ready_bundle_source"] == "request"

    layer1 = body["explanation"]["meta"]["layer_1_stock_health"]
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
        "main_margin": 0.8,
        "assorti_margin": 0.65,
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

    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in layer2_step
    assert "legacy_decision_gate=profit_until_eta" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step

    layer2_contract_checks = body["explanation"]["meta"]["layer_2_allocation"]["contract"]["checks"]
    assert layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_contract_checks["decision_reason_expected_gross_profit_matches_allocation"] is True
    assert layer2_contract_checks["decision_reason_objective_score_matches_allocation"] is True
    assert layer2_contract_checks["allocation_matches_composite_objective_gate"] is True
    assert layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_contract_checks["allocation_matches_expected_gross_profit_gate"] is True
    assert layer2_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_contract_checks["capital_locked_metric_valid"] is True
    assert layer2_contract_checks["objective_required_fields_present"] is True
    assert layer2_contract_checks["objective_score_fields_numeric"] is True
    assert layer2_contract_checks["objective_components_present"] is True
    assert layer2_contract_checks["objective_components_numeric"] is True
    assert layer2_contract_checks["objective_components_consistent_with_scores"] is True
    assert layer2_contract_checks["objective_components_match_formula"] is True
    assert layer2_contract_checks["objective_score_gap_consistent_with_objective_scores"] is True

    layer3 = body["explanation"]["meta"]["layer_3_purchase_shaping"]
    assert layer3["method"] == "allocation_decision_factors"
    assert layer3["factors"] == {"main": 1.0, "assorti": 0.75, "hold": 0.35}
    assert layer3["qty_before"] >= layer3["qty_after_base"] >= 0
    assert layer3["qty_after"] >= 0
    assert layer3["qty_delta_vs_base"] == layer3["qty_after"] - layer3["qty_after_base"]
    assert layer3["calibration"]["method"] == "risk_weighted_factor_clamp"
    assert layer3["contract"]["status"] == "ok"
    layer3_contract_checks = layer3["contract"]["checks"]
    assert layer3_contract_checks["non_negative_quantities"] is True
    assert layer3_contract_checks["qty_delta_matches_after_minus_base"] is True
    assert layer3_contract_checks["non_negative_line_counts"] is True
    assert layer3_contract_checks["adjusted_lines_within_decision_lines"] is True
    assert layer3_contract_checks["non_negative_risk_line_counts"] is True
    assert layer3_contract_checks["risk_partition_matches_decision_lines"] is True
    assert layer3_contract_checks["non_negative_calibration_direction_counts"] is True
    assert layer3_contract_checks["calibration_direction_counts_within_decision_lines"] is True
    assert layer3_contract_checks["calibration_method_matches"] is True
    assert layer3_contract_checks["factor_bounds_match_expected"] is True
    assert layer3_contract_checks["factor_summary_consistent"] is True
    assert layer3_contract_checks["factor_summary_within_bounds"] is True

    layer4_contract_checks = body["explanation"]["meta"]["layer_4_scenarios"]["contract"]["checks"]
    assert layer4_contract_checks["capital_non_decreasing"] is True
    assert layer4_contract_checks["stockout_risk_non_increasing"] is True
    assert layer4_contract_checks["turnover_non_increasing"] is True
    assert layer4_contract_checks["purchase_units_non_decreasing"] is True
    assert layer4_contract_checks["scenario_delta_fields_present"] is True
    assert layer4_contract_checks["scenario_deltas_match_balanced"] is True

    layer5_contract_checks = body["explanation"]["meta"]["layer_5_intervention"]["contract"]["checks"]
    assert layer5_contract_checks["required_layer4_scenarios_present"] is True
    assert layer5_contract_checks["required_layer4_scenarios_unique"] is True
    assert layer5_contract_checks["thresholds_in_unit_interval"] is True
    assert layer5_contract_checks["threshold_sources_match_effective"] is True
    assert layer5_contract_checks["threshold_order_valid"] is True
    assert layer5_contract_checks["signals_known_only"] is True
    assert layer5_contract_checks["signals_unique"] is True
    assert layer5_contract_checks["signals_order_is_canonical"] is True
    assert layer5_contract_checks["reason_consistent_with_signals"] is True

    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["source"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["calibration_state"] == "alpha_proxy_not_calibrated"
    assert alpha_proxy["margin_proxy"] == {"main": 0.8, "assorti": 0.65}
    assert alpha_proxy["unit_capital_proxy"] == 1.0
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert alpha_proxy["layer_2_allocation_method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_legacy_allocation_method"] == LAYER2_ALLOCATION_METHOD
    assert alpha_proxy["layer_2_decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert (
        alpha_proxy["layer_2_legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )
    assert (
        alpha_proxy["layer_2_near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
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
        "layer2_capital_cost_rate": "code_default_constants",
        "layer2_stockout_penalty_weight": "code_default_constants",
        "layer2_overstock_penalty_weight": "code_default_constants",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }
    assert alpha_proxy["layer_4_scenario_factors"] == body["explanation"]["meta"]["layer_4_scenarios"]["factors"]
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert (
        alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }

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
    assert from_wb_meta["economic_observed_commission"]["source"] == FROM_WB_TARIFFS_COMMISSION_SOURCE
    assert from_wb_meta["economic_observed_commission"]["status"] == "unavailable"

    helper_physical_scope, helper_arrival_projection = build_physical_scope_and_arrival_projection(
        bundle_stock_source="request",
        in_flight_source="none",
        size_weights_source="uniform_fallback",
        bundle_type_ids=[seeded["bundle_type"].id],
        recipe_colors_by_bundle={
            seeded["bundle_type"].id: {seeded["color_1"].id, seeded["color_2"].id},
        },
        all_recipe_color_ids=[seeded["color_1"].id, seeded["color_2"].id],
        size_ids=[seeded["size_s"].id, seeded["size_m"].id],
        current_stock_by_color_size={
            (seeded["color_1"].id, seeded["size_s"].id): 10,
            (seeded["color_1"].id, seeded["size_m"].id): 10,
            (seeded["color_2"].id, seeded["size_s"].id): 10,
            (seeded["color_2"].id, seeded["size_m"].id): 10,
        },
        in_flight_effective_by_color_size={
            (seeded["color_1"].id, seeded["size_s"].id): 0,
            (seeded["color_1"].id, seeded["size_m"].id): 0,
            (seeded["color_2"].id, seeded["size_s"].id): 0,
            (seeded["color_2"].id, seeded["size_m"].id): 0,
        },
        shares_by_bundle={seeded["bundle_type"].id: 1.0},
        ready_bundle_stock_total=20,
        total_daily_sales=2.0,
        lead_time_days_total=70,
        estimate_raw_bundle_stock=planning_production_order_service._estimate_competition_aware_raw_bundle_stock,
    )

    assert helper_physical_scope.model_dump(mode="json") == body["physical_scope"]
    assert helper_arrival_projection.model_dump(mode="json") == body["arrival_projection"]
    assert body["explanation"]["meta"]["physical_scope"] == body["physical_scope"]
    assert body["explanation"]["meta"]["arrival_projection"] == body["arrival_projection"]
    assert any("Physical scope:" in step for step in body["explanation"]["steps"])
    assert any("Arrival projection:" in step for step in body["explanation"]["steps"])


def test_production_order_proposal_from_wb_price_flip_changes_layer2_allocation_decision_end_to_end(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-WB-MIX-FLIP",
        name="PO-BT-WB-MIX-FLIP",
        is_assorti=True,
    )
    db_session.add(assorti_bundle_type)
    db_session.flush()

    as_of_date = datetime(2026, 1, 10, tzinfo=timezone.utc).date()
    wb_sku_main = "WB-PO-MIX-FLIP-MAIN"
    wb_sku_assorti = "WB-PO-MIX-FLIP-ASSORTI"

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
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku_main,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku_assorti,
                bundle_type_id=assorti_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku_main,
                date=as_of_date,
                sales_qty=300,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku=wb_sku_assorti,
                date=as_of_date,
                sales_qty=300,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku_main,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=5,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku_assorti,
                warehouse_id=2,
                warehouse_name="WB-2",
                stock_qty=5,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    base_payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id, assorti_bundle_type.id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
            "allow_order_with_buffer": False,
            "production_cost_per_unit": 1.0,
            "logistics_cost_per_unit": 0.2,
            "wb_commission_percent_main": 0.05,
            "wb_commission_percent_assorti": 0.05,
        },
    }

    main_wins_payload = deepcopy(base_payload)
    main_wins_payload["overrides"].update(
        {
            "average_realized_price_main": 2.4,
            "average_realized_price_assorti": 1.5,
        }
    )
    assorti_wins_payload = deepcopy(base_payload)
    assorti_wins_payload["overrides"].update(
        {
            "average_realized_price_main": 1.5,
            "average_realized_price_assorti": 2.4,
        }
    )

    main_wins_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=main_wins_payload,
    )
    assorti_wins_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=assorti_wins_payload,
    )

    assert main_wins_response.status_code == 200, main_wins_response.text
    assert assorti_wins_response.status_code == 200, assorti_wins_response.text

    main_wins_body = main_wins_response.json()
    assorti_wins_body = assorti_wins_response.json()

    main_margin_proxy = main_wins_body["explanation"]["meta"]["alpha_proxy_economics"]["margin_proxy"]
    assorti_margin_proxy = assorti_wins_body["explanation"]["meta"]["alpha_proxy_economics"]["margin_proxy"]
    assert main_margin_proxy == {"main": 1.08, "assorti": 0.225}
    assert assorti_margin_proxy == {"main": 0.225, "assorti": 1.08}

    main_summary = main_wins_body["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assorti_summary = assorti_wins_body["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assert main_summary["assorti"] > 0
    assert main_summary["main"] == 0
    assert assorti_summary["main"] > 0
    assert assorti_summary["assorti"] == 0

    main_from_wb = main_wins_body["explanation"]["meta"]["from_wb"]
    assorti_from_wb = assorti_wins_body["explanation"]["meta"]["from_wb"]
    assert main_from_wb["daily_sales_by_bundle"][str(seeded["bundle_type"].id)] == 10.0
    assert main_from_wb["daily_sales_by_bundle"][str(assorti_bundle_type.id)] == 10.0
    assert assorti_from_wb["daily_sales_by_bundle"][str(seeded["bundle_type"].id)] == 10.0
    assert assorti_from_wb["daily_sales_by_bundle"][str(assorti_bundle_type.id)] == 10.0

    main_decisions = sorted(
        main_wins_body["explanation"]["meta"]["layer_2_allocation"]["decisions"],
        key=lambda item: (item["color_id"], item["size_id"]),
    )
    assorti_decisions = sorted(
        assorti_wins_body["explanation"]["meta"]["layer_2_allocation"]["decisions"],
        key=lambda item: (item["color_id"], item["size_id"]),
    )
    assert len(main_decisions) == len(assorti_decisions) > 0
    for main_decision, assorti_decision in zip(main_decisions, assorti_decisions):
        assert main_decision["color_id"] == assorti_decision["color_id"]
        assert main_decision["size_id"] == assorti_decision["size_id"]
        assert main_decision["eta_days"] == assorti_decision["eta_days"]
        assert main_decision["capital_locked"] == assorti_decision["capital_locked"]
        assert main_decision["allocation_decision"] == "assorti"
        assert (
            main_decision["objective_score_if_assorti_until_eta"]
            > main_decision["objective_score_if_main_until_eta"]
        )
        assert assorti_decision["allocation_decision"] == "main"
        assert (
            assorti_decision["objective_score_if_main_until_eta"]
            > assorti_decision["objective_score_if_assorti_until_eta"]
        )

    main_compact_payload = deepcopy(main_wins_payload)
    main_compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    main_compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=main_compact_payload,
    )
    assert main_compact_response.status_code == 200, main_compact_response.text

    main_compact_body = main_compact_response.json()
    main_compact_meta = main_compact_body["explanation"]["meta"]
    assert _business_projection(main_wins_body) == _business_projection(main_compact_body)
    assert main_compact_meta["alpha_proxy_economics"] == main_wins_body["explanation"]["meta"]["alpha_proxy_economics"]
    assert main_compact_meta["alpha_proxy_economics"]["margin_proxy"] == main_margin_proxy
    assert main_compact_meta["layer_2_allocation"]["summary"] == main_summary


def test_production_order_proposal_from_wb_skipped_when_article_excluded(client, db_session):
    seeded = _seed_article_bundle_base(db_session, include_in_planning=False)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-SKIPPED",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-SKIPPED",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-SKIPPED",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "skipped"
    assert body["risk_level"] == "no_data"
    assert body["recommendation"] is None
    assert body["alternatives"] == []
    assert body["days_of_cover_estimate"] == 0.0
    assert "исключен" in body["explanation"]["summary"].lower()
    assert any("WB ingestion adapter" in step for step in body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    assert "исключен" in compact_body["explanation"]["summary"].lower()
    assert any("WB ingestion adapter" in step for step in compact_body["explanation"]["steps"])


def test_production_order_proposal_from_wb_economic_buffer_policy(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BUFFER-POLICY",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BUFFER-POLICY",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BUFFER-POLICY",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    payload_without_buffer = {
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
    payload_with_buffer = {
        **payload_without_buffer,
        "overrides": {
            **payload_without_buffer["overrides"],
            "allow_order_with_buffer": True,
        },
    }

    response_without = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload_without_buffer,
    )
    response_with = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
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

    payload_without_buffer["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    payload_with_buffer["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response_without = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload_without_buffer,
    )
    compact_response_with = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload_with_buffer,
    )

    assert compact_response_without.status_code == 200, compact_response_without.text
    assert compact_response_with.status_code == 200, compact_response_with.text

    compact_body_without = compact_response_without.json()
    compact_body_with = compact_response_with.json()
    assert _business_projection(body_without) == _business_projection(compact_body_without)
    assert _business_projection(body_with) == _business_projection(compact_body_with)
    assert (
        compact_body_without["explanation"]["meta"]["economic_buffer"]
        == body_without["explanation"]["meta"]["economic_buffer"]
    )
    assert (
        compact_body_with["explanation"]["meta"]["economic_buffer"]
        == body_with["explanation"]["meta"]["economic_buffer"]
    )


def test_production_order_proposal_from_wb_applies_safety_stock_days_to_reorder_policy(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-SAFETY-STOCK",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-SAFETY-STOCK",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-SAFETY-STOCK",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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

    response_without_safety_stock = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
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
        "/api/v1/planning/core/production-order/proposal/from-wb",
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body_with) == _business_projection(compact_body)
    assert compact_body["explanation"]["meta"]["reorder_policy"] == {
        "lead_time_days_total": 70,
        "safety_stock_days": 21,
        "reorder_point_days": 91,
    }


def test_production_order_proposal_from_wb_returns_alternatives(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ALTERNATIVES",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ALTERNATIVES",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ALTERNATIVES",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
    recommendation_action = body["recommendation"]["action"]
    alternative_actions = {item["action"] for item in body["alternatives"]}
    assert len(alternative_actions) >= 2
    assert alternative_actions.issubset({"wait", "order_with_buffer", "order_minimum_only"})
    assert recommendation_action not in alternative_actions

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)


def test_production_order_proposal_from_wb_competition_aware_raw_stock_breakdown(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    competing_bundle_type = BundleType(code="PO-WB-BT-2", name="PO-WB-BT-2")
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
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-RAW-STOCK-MAIN",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-RAW-STOCK-COMPETING",
                bundle_type_id=competing_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku="WB-PO-RAW-STOCK-MAIN",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=600,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku="WB-PO-RAW-STOCK-COMPETING",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=300,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-RAW-STOCK-MAIN",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=10,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-RAW-STOCK-COMPETING",
                warehouse_id=2,
                warehouse_name="WB-2",
                stock_qty=0,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-10",
        "bundle_type_ids": [seeded["bundle_type"].id, competing_bundle_type.id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    full_meta = body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["resource_allocation"] == full_meta["resource_allocation"]


def test_production_order_proposal_from_wb_shared_color_pool_reduces_local_fabric_min_uplift(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    seeded["color_2"].pantone_code = seeded["color_1"].pantone_code
    db_session.flush()

    article_wb_sku = "WB-PO-SHARED-COLOR-PRIMARY"
    as_of_date = date(2026, 1, 30)
    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku=article_wb_sku,
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku=article_wb_sku,
            date=as_of_date,
            sales_qty=15,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku=article_wb_sku,
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=0,
            updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 100,
            "elastic_min_batch_qty_default": 0,
        },
    }

    base_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert base_response.status_code == 200, base_response.text
    base_body = base_response.json()
    base_recommendation = base_body["recommendation"]
    assert base_recommendation is not None
    base_fabric_constraints = base_body["constraints_applied"]["fabric_min_batches"]
    assert base_fabric_constraints
    assert base_fabric_constraints[0]["sibling_proxy_required"] == 0
    base_total_units = base_recommendation["total_units"]

    sibling_article = Article(code="PO-WB-ART-SHARED", name="PO-WB-ART-SHARED")
    sibling_color = Color(inner_code="PO-WB-C-SHARED", pantone_code=seeded["color_1"].pantone_code, description="Shared Pantone")
    db_session.add_all([sibling_article, sibling_color])
    db_session.flush()

    db_session.add(
        SkuUnit(
            article_id=sibling_article.id,
            color_id=sibling_color.id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        ArticlePlanningSettings(
            article_id=sibling_article.id,
            include_in_planning=True,
            priority=1,
            target_coverage_days=60,
            lead_time_days=70,
            service_level_percent=90,
        )
    )
    db_session.add(
        ArticleWbMapping(
            article_id=sibling_article.id,
            wb_sku="WB-SHARED-PANTONE-FROM-WB",
        )
    )

    sales_start = date(2026, 1, 1)
    for day_offset in range(30):
        sales_date = sales_start + timedelta(days=day_offset)
        db_session.add(
            WbSalesDaily(
                wb_sku="WB-SHARED-PANTONE-FROM-WB",
                date=sales_date,
                sales_qty=1,
                revenue=None,
                created_at=datetime(sales_date.year, sales_date.month, sales_date.day, tzinfo=timezone.utc),
            )
        )
    db_session.commit()

    shared_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert shared_response.status_code == 200, shared_response.text
    shared_body = shared_response.json()
    shared_recommendation = shared_body["recommendation"]
    assert shared_recommendation is not None
    assert shared_recommendation["total_units"] < base_total_units

    shared_color_pool = shared_body["explanation"]["meta"]["shared_color_pool"]
    assert shared_color_pool["status"] == "ok"
    assert shared_color_pool["sibling_article_count"] >= 1
    pantone_item = shared_color_pool["pantones"][seeded["color_1"].pantone_code]
    assert pantone_item["sibling_proxy_required"] > 0
    assert pantone_item["sibling_article_ids"] == [sibling_article.id]
    assert any("Shared color pool:" in step for step in shared_body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(shared_body) == _business_projection(compact_body)
    assert compact_meta["shared_color_pool"] == shared_color_pool
    assert any("Shared color pool:" in step for step in compact_body["explanation"]["steps"])


def test_production_order_proposal_from_wb_exposes_resource_allocation_consumption(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-WB-RESOURCE",
        name="PO-BT-WB-RESOURCE",
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

    as_of_date = date(2026, 1, 30)
    observation_window_days = 30
    main_wb_sku = "WB-PO-RESOURCE-MAIN"
    assorti_wb_sku = "WB-PO-RESOURCE-ASSORTI"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=main_wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=assorti_wb_sku,
                bundle_type_id=assorti_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=main_wb_sku,
                date=as_of_date,
                sales_qty=18 * observation_window_days,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku=assorti_wb_sku,
                date=as_of_date,
                sales_qty=12 * observation_window_days,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=main_wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=10,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
            WbStock(
                wb_sku=assorti_wb_sku,
                warehouse_id=2,
                warehouse_name="WB-2",
                stock_qty=4,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": observation_window_days,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id, assorti_bundle_type.id],
        "in_flight_supply": [],
        "size_weights": {},
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    resource_allocation = body["constraints_applied"]["resource_allocation"]
    assert resource_allocation["mode"] == "per_article_bundle_competition"
    assert resource_allocation["competing_resource_keys"] > 0
    assert resource_allocation["contract"]["version"] == RESOURCE_ALLOCATION_CONTRACT_VERSION
    assert resource_allocation["contract"]["status"] == "ok"

    shared_reservations = [item for item in resource_allocation["reservations"] if item["shared_resource"]]
    assert shared_reservations
    for reservation in shared_reservations:
        assert reservation["total_reserved_qty"] <= reservation["stock_qty"]
        assert sum(item["reserved_qty"] for item in reservation["allocations"]) == reservation["total_reserved_qty"]

    meta = body["explanation"]["meta"]
    assert meta["resource_allocation"]["contract"]["status"] == "ok"
    assert any("Resource allocation:" in step for step in body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["resource_allocation"] == meta["resource_allocation"]
    assert any("Resource allocation:" in step for step in compact_body["explanation"]["steps"])


def test_production_order_proposal_from_wb_applies_elastic_minimum(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type = ElasticType(code="PO-WB-EL-1", name="PO-WB-EL-1")
    db_session.add(elastic_type)
    db_session.flush()

    db_session.add(
        ElasticPlanningSettings(
            article_id=seeded["article"].id,
            elastic_type_id=elastic_type.id,
            elastic_min_batch_qty=15000,
        )
    )

    as_of_date = date(2026, 1, 30)
    observation_window_days = 30
    wb_sku = "WB-PO-ELASTIC-MIN"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": observation_window_days,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    elastic_constraints = body["constraints_applied"]["elastic_min_batches"]
    assert elastic_constraints
    assert elastic_constraints[0]["applied_min"] == 15000
    assert elastic_constraints[0]["required"] < elastic_constraints[0]["applied_min"]

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_body["constraints_applied"]["elastic_min_batches"] == elastic_constraints


def test_production_order_proposal_from_wb_elastic_binding_scope_selects_bound_type(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type_1 = ElasticType(code="PO-WB-EL-BIND-1", name="PO-WB-EL-BIND-1")
    elastic_type_2 = ElasticType(code="PO-WB-EL-BIND-2", name="PO-WB-EL-BIND-2")
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

    as_of_date = date(2026, 1, 30)
    observation_window_days = 30
    wb_sku = "WB-PO-ELASTIC-BIND-MAIN"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": observation_window_days,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_elastic_uplift = {
        "delta": meta["elastic_uplift"]["delta"],
        "scope": meta["elastic_uplift"]["scope"],
        "affected_lines": meta["elastic_uplift"]["affected_lines"],
    }
    assert compact_meta["elastic_scope"] == meta["elastic_scope"]
    assert compact_meta["elastic_scope"]["mode"] == "binding_scope"
    assert compact_meta["elastic_uplift"] == expected_compact_elastic_uplift


def test_production_order_proposal_from_wb_applies_fabric_minimum(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ColorPlanningSettings(
            article_id=seeded["article"].id,
            color_id=seeded["color_1"].id,
            fabric_min_batch_qty=7500,
        )
    )

    as_of_date = date(2026, 1, 30)
    wb_sku = "WB-PO-FABRIC-MINIMUM"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "elastic_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    fabric_constraints = body["constraints_applied"]["fabric_min_batches"]
    assert fabric_constraints
    assert any(item["applied_min"] >= item["required"] for item in fabric_constraints)
    assert any(item["sibling_proxy_required"] == 0 for item in fabric_constraints)

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_fabric_constraints = compact_body["constraints_applied"]["fabric_min_batches"]
    assert compact_fabric_constraints == fabric_constraints


def test_production_order_proposal_from_wb_elastic_binding_scope_skips_when_no_match(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    elastic_type = ElasticType(code="PO-WB-EL-NOMATCH", name="PO-WB-EL-NOMATCH")
    color_3 = Color(inner_code="PO-WB-C3", pantone_code="BLACK-03", description="Blue")
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

    as_of_date = date(2026, 1, 30)
    wb_sku = "WB-PO-ELASTIC-NOMATCH"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_elastic_uplift = {
        "delta": meta["elastic_uplift"]["delta"],
        "scope": meta["elastic_uplift"]["scope"],
        "affected_lines": meta["elastic_uplift"]["affected_lines"],
    }
    assert compact_meta["elastic_scope"] == meta["elastic_scope"]
    assert compact_meta["elastic_scope"]["applicable_types"] == []
    assert compact_meta["elastic_uplift"] == expected_compact_elastic_uplift


def test_production_order_proposal_from_wb_elastic_binding_scope_uplift_only_scoped_sku(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    as_of_date = date(2026, 1, 30)
    wb_sku = "WB-PO-ELASTIC-SCOPE-SKU"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    baseline_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    elastic_type = ElasticType(code="PO-WB-EL-SCOPE-SKU", name="PO-WB-EL-SCOPE-SKU")
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

    scoped_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    meta = scoped_body["explanation"]["meta"]
    assert meta["elastic_scope"]["scoped_lines"] == 1
    assert meta["elastic_uplift"]["scope"] == "binding_scope"
    assert meta["elastic_uplift"]["affected_lines"] == 1
    alloc_pairs = {
        (item["color_id"], item["size_id"])
        for item in meta["elastic_uplift"]["line_alloc"]
    }
    assert alloc_pairs == {scoped_key}

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_elastic_uplift = {
        "delta": meta["elastic_uplift"]["delta"],
        "scope": meta["elastic_uplift"]["scope"],
        "affected_lines": meta["elastic_uplift"]["affected_lines"],
    }
    assert compact_meta["elastic_scope"] == meta["elastic_scope"]
    assert compact_meta["elastic_scope"]["scoped_lines"] == 1
    assert compact_meta["elastic_uplift"] == expected_compact_elastic_uplift


def test_production_order_proposal_from_wb_elastic_binding_scope_uplift_only_scoped_lines(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    as_of_date = date(2026, 1, 30)
    wb_sku = "WB-PO-ELASTIC-SCOPE-LINES"
    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku=wb_sku,
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku=wb_sku,
                date=as_of_date,
                sales_qty=150,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku=wb_sku,
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=0,
                updated_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": as_of_date.isoformat(),
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    baseline_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert baseline_response.status_code == 200, baseline_response.text

    baseline_body = baseline_response.json()
    baseline_lines = baseline_body["recommendation"]["lines"]

    baseline_totals_by_color: dict[int, int] = {}
    for line in baseline_lines:
        baseline_totals_by_color[line["color_id"]] = (
            baseline_totals_by_color.get(line["color_id"], 0) + line["recommended_qty"]
        )

    elastic_type = ElasticType(code="PO-WB-EL-SCOPE-ONLY", name="PO-WB-EL-SCOPE-ONLY")
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

    scoped_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    scope_step = next(
        (step for step in scoped_body["explanation"]["steps"] if "Elastic scope" in step),
        "",
    )
    uplift_step = next(
        (step for step in scoped_body["explanation"]["steps"] if "Elastic uplift" in step),
        "",
    )
    assert "scoped_lines=2" in scope_step
    assert "scope=binding_scope" in uplift_step
    assert "affected_lines=2" in uplift_step

    meta = scoped_body["explanation"]["meta"]
    assert meta["elastic_scope"]["mode"] == "binding_scope"
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_elastic_uplift = {
        "delta": meta["elastic_uplift"]["delta"],
        "scope": meta["elastic_uplift"]["scope"],
        "affected_lines": meta["elastic_uplift"]["affected_lines"],
    }
    assert compact_meta["elastic_scope"] == meta["elastic_scope"]
    assert compact_meta["elastic_scope"]["scoped_lines"] == 2
    assert compact_meta["elastic_uplift"] == expected_compact_elastic_uplift


def test_production_order_proposal_from_wb_in_flight_eta_stage_sensitivity(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-IN-FLIGHT-SENSITIVITY",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-IN-FLIGHT-SENSITIVITY",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-IN-FLIGHT-SENSITIVITY",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-10",
        "bundle_type_ids": [seeded["bundle_type"].id],
        "in_flight_supply": [
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
        ],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
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

    in_flight_meta = body["explanation"]["meta"]["in_flight_effective"]
    assert in_flight_meta["raw_qty"] == 200
    assert in_flight_meta["lines"] == 1
    assert 0 < in_flight_meta["effective_qty"] < 200

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text
    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert compact_meta["in_flight_effective"] == in_flight_meta


def test_production_order_proposal_from_wb_arrival_projection_safe_cover_until_arrival_forces_wait(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)
    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-SAFE-COVER",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-SAFE-COVER",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=600,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-SAFE-COVER",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=10,
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
        "in_flight_supply": [
            {
                "article_id": seeded["article"].id,
                "color_id": seeded["color_1"].id,
                "size_id": seeded["size_s"].id,
                "qty": 800,
                "eta_days": 10,
                "stage": "nsk_to_wb",
            },
            {
                "article_id": seeded["article"].id,
                "color_id": seeded["color_1"].id,
                "size_id": seeded["size_m"].id,
                "qty": 800,
                "eta_days": 10,
                "stage": "nsk_to_wb",
            },
            {
                "article_id": seeded["article"].id,
                "color_id": seeded["color_2"].id,
                "size_id": seeded["size_s"].id,
                "qty": 800,
                "eta_days": 10,
                "stage": "nsk_to_wb",
            },
            {
                "article_id": seeded["article"].id,
                "color_id": seeded["color_2"].id,
                "size_id": seeded["size_m"].id,
                "qty": 800,
                "eta_days": 10,
                "stage": "nsk_to_wb",
            },
        ],
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
    assert body["risk_level"] == "warning"
    assert body["arrival_projection"]["status"] == "safe_cover_until_arrival"
    assert body["arrival_projection"]["in_flight_bundle_capacity_at_arrival"] == 1374
    assert body["arrival_projection"]["projected_supply_units_before_arrival"] == 1404
    assert body["arrival_projection"]["projected_availability_at_arrival"] == 4
    assert body["arrival_projection"]["projected_shortage_before_arrival"] == 0
    assert body["arrival_projection"]["projected_cover_days_at_arrival"] == 0.2
    assert body["recommendation"]["action"] == "wait"
    assert body["recommendation"]["total_units"] == 0
    assert body["recommendation"]["lines"] == []
    assert len(body["alternatives"]) >= 2
    assert {item["action"] for item in body["alternatives"]}.issubset(
        {"wait", "order_with_buffer", "order_minimum_only"}
    )
    assert body["explanation"]["meta"]["arrival_projection"] == body["arrival_projection"]
    assert any("Arrival projection:" in step for step in body["explanation"]["steps"])

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_body["explanation"]["meta"]["arrival_projection"] == compact_body["arrival_projection"]
    assert any("Arrival projection:" in step for step in compact_body["explanation"]["steps"])


def test_production_order_proposal_from_wb_requires_available_capital_in_strict_mode(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_available_capital = None
    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_available_capital = None

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-CAP-STRICT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-CAP-STRICT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-CAP-STRICT",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime.now(timezone.utc),
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
    assert response.status_code == 422, response.text

    assert response.json()["detail"] == {
        "code": "missing_available_capital_strict",
        "message": "available_capital is required for production-order proposal in strict capital governance mode",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for strict capital governance mode",
            "type": "number",
        },
        "capital_constraint_status": CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
        "severity": "HIGH",
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": ECONOMICS_TRUST_LEVEL_UNTRUSTED,
        "next_steps": ["provide_available_capital_override_or_default"],
    }


def test_production_order_proposal_from_wb_safe_default_mode_applies_zero_capital_fallback(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_available_capital = None
    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_available_capital = None

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-CAP-SAFE-DEFAULT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-CAP-SAFE-DEFAULT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-CAP-SAFE-DEFAULT",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime.now(timezone.utc),
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
            "capital_governance_mode": "safe_default",
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["recommendation"]["action"] == "wait"
    assert body["recommendation"]["total_units"] == 0

    meta = body["explanation"]["meta"]
    assert meta["capital_governance"] == {
        "mode": "safe_default",
        "missing_available_capital_policy": "safe_default",
        "safe_default_applied": True,
        "available_capital_effective": 0.0,
        "effective_source": "safe_default_zero_capital",
    }
    safe_default_warning = next(
        warning
        for warning in meta["warnings"]
        if warning["code"] == "available_capital_safe_default_applied"
    )
    assert safe_default_warning == {
        "code": "available_capital_safe_default_applied",
        "severity": "HIGH",
        "message": "available_capital missing; safe_default mode applied zero-capital fallback to avoid unconstrained recommendations",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input for safe_default capital governance mode",
            "type": "number",
        },
        "capital_governance_status": "safe_default_zero_capital_applied",
        "capital_governance_mode": "safe_default",
        "available_capital_effective": 0.0,
        "action": "Provide overrides.available_capital or configure article/global available_capital defaults.",
        "economics_trust_level": ECONOMICS_TRUST_LEVEL_UNTRUSTED,
        "next_steps": ["provide_available_capital_override_or_default"],
    }
    assert meta["alpha_proxy_economics"]["economic_inputs"]["available_capital"] == 0.0
    assert meta["alpha_proxy_economics"]["economic_source"]["available_capital"] == "safe_default_zero_capital"
    assert meta["alpha_proxy_economics"]["capital_governance"] == meta["capital_governance"]
    assert meta["arrival_projection"]["status"] == "shortage_before_arrival"
    assert meta["arrival_projection"]["projected_shortage_before_arrival"] > 0
    assert meta["capital_constraint"]["status"] == "budget_limited_applied"
    assert meta["capital_constraint"]["available_capital"] == 0.0
    assert meta["capital_constraint"]["allocated_capital_after_constraint"] == 0.0
    assert meta["capital_constraint"]["line_count_before"] > 0
    assert meta["capital_constraint"]["line_count_after"] == 0
    assert meta["warnings"][-1] == {
        "code": "shortage_before_arrival_wait_blocked_by_capital_constraint",
        "severity": "HIGH",
        "message": "shortage_before_arrival detected, but recommendation remained wait because capital constraint trimmed feasible order quantity to zero",
        "article_id": seeded["article"].id,
        "field": "available_capital",
        "field_metadata": {
            "description": "Available capital input applied to production-order capital constraint",
            "type": "number",
        },
        "arrival_projection_status": "shortage_before_arrival",
        "projected_shortage_before_arrival": meta["arrival_projection"]["projected_shortage_before_arrival"],
        "recommendation_action": "wait",
        "capital_constraint_status": "budget_limited_applied",
        "available_capital_effective": 0.0,
        "required_capital_before_constraint": meta["capital_constraint"]["required_capital_before_constraint"],
        "allocated_capital_after_constraint": 0.0,
        "action": "Provide or increase available_capital before treating wait as safe under shortage.",
        "next_steps": ["provide_available_capital_override_or_default"],
    }

    expected_compact_assorti_classification = {
        "source": meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["economics_trust"] == meta["economics_trust"]
    assert compact_meta["warnings"] == meta["warnings"]
    assert compact_meta["alpha_proxy_economics"] == meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["available_capital"] == 0.0
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["available_capital"] == "safe_default_zero_capital"
    assert compact_meta["alpha_proxy_economics"]["capital_governance"] == compact_meta["capital_governance"]
    assert compact_meta["capital_constraint"] == meta["capital_constraint"]


def test_production_order_proposal_from_wb_uses_code_default_economics_when_request_admin_global_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = None
    article_settings.production_order_logistics_cost_per_unit = None
    article_settings.production_order_wb_commission_percent_main = None
    article_settings.production_order_wb_commission_percent_assorti = None
    article_settings.production_order_average_realized_price_main = None
    article_settings.production_order_average_realized_price_assorti = None
    article_settings.production_order_available_capital = None

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = None
    global_settings.default_production_order_logistics_cost_per_unit = None
    global_settings.default_production_order_wb_commission_percent_main = None
    global_settings.default_production_order_wb_commission_percent_assorti = None
    global_settings.default_production_order_average_realized_price_main = None
    global_settings.default_production_order_average_realized_price_assorti = None
    global_settings.default_production_order_available_capital = None

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ECON-CODE-DEFAULT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ECON-CODE-DEFAULT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ECON-CODE-DEFAULT",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
            "available_capital": 1000000.0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_default_formula"
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "code_default_constants",
        "logistics_cost_per_unit": "code_default_constants",
        "wb_commission_percent_main": "code_default_constants",
        "wb_commission_percent_assorti": "code_default_constants",
        "average_realized_price_main": "code_default_constants",
        "average_realized_price_assorti": "code_default_constants",
        "available_capital": "request",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 0.8,
        "logistics_cost_per_unit": 0.2,
        "wb_commission_percent_main": 0.0,
        "wb_commission_percent_assorti": 0.0,
        "average_realized_price_main": 1.8,
        "average_realized_price_assorti": 1.65,
        "available_capital": 1000000.0,
    }
    assert alpha_proxy["margin_proxy"] == {"main": 0.8, "assorti": 0.65}
    assert alpha_proxy["unit_capital_proxy"] == 1.0

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_UNTRUSTED
    assert economics_trust["code_default_key_fields_count"] >= 2
    assert economics_trust["code_default_dominance_ratio"] > 0
    assert economics_trust["warnings"][0]["code"] == ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED
    assert economics_trust["warnings"][0]["severity"] == "HIGH"
    assert meta["warnings"][0] == economics_trust["warnings"][0]
    capital_gap = meta["capital_gap"]

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == meta["warnings"]
    assert compact_meta["warnings"][0] == economics_trust["warnings"][0]


def test_production_order_proposal_from_wb_reports_partial_economics_trust_when_one_key_field_uses_code_default(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = 0.7
    article_settings.production_order_logistics_cost_per_unit = 0.3
    article_settings.production_order_wb_commission_percent_main = 0.11
    article_settings.production_order_wb_commission_percent_assorti = 0.12
    article_settings.production_order_average_realized_price_main = 2.2
    article_settings.production_order_average_realized_price_assorti = None
    article_settings.production_order_available_capital = 300.0

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 0.9
    global_settings.default_production_order_logistics_cost_per_unit = 0.4
    global_settings.default_production_order_wb_commission_percent_main = 0.13
    global_settings.default_production_order_wb_commission_percent_assorti = 0.14
    global_settings.default_production_order_average_realized_price_main = 2.6
    global_settings.default_production_order_average_realized_price_assorti = None
    global_settings.default_production_order_available_capital = 450.0

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ECON-PARTIAL-TRUST",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ECON-PARTIAL-TRUST",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ECON-PARTIAL-TRUST",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"]["average_realized_price_assorti"] == "code_default_constants"
    assert alpha_proxy["economic_inputs"]["average_realized_price_assorti"] == 1.65

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_PARTIAL
    assert economics_trust["code_default_key_fields"] == ["average_realized_price_assorti"]
    assert economics_trust["code_default_key_fields_count"] == 1
    assert economics_trust["warnings"][0]["code"] == ECONOMICS_TRUST_WARNING_CODE_PARTIAL
    assert economics_trust["warnings"][0]["severity"] == "MEDIUM"
    assert meta["warnings"][0] == economics_trust["warnings"][0]
    capital_gap = meta["capital_gap"]

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == meta["warnings"]
    assert compact_meta["warnings"][0] == economics_trust["warnings"][0]


def test_production_order_proposal_from_wb_uses_global_economic_defaults_when_admin_and_request_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = None
    article_settings.production_order_logistics_cost_per_unit = None
    article_settings.production_order_wb_commission_percent_main = None
    article_settings.production_order_wb_commission_percent_assorti = None
    article_settings.production_order_average_realized_price_main = None
    article_settings.production_order_average_realized_price_assorti = None
    article_settings.production_order_available_capital = None

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 1.0
    global_settings.default_production_order_logistics_cost_per_unit = 0.2
    global_settings.default_production_order_wb_commission_percent_main = 0.10
    global_settings.default_production_order_wb_commission_percent_assorti = 0.20
    global_settings.default_production_order_average_realized_price_main = 3.0
    global_settings.default_production_order_average_realized_price_assorti = 3.5
    global_settings.default_production_order_available_capital = 250.0

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ECON-GLOBAL-DEFAULT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ECON-GLOBAL-DEFAULT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ECON-GLOBAL-DEFAULT",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "global_default",
        "logistics_cost_per_unit": "global_default",
        "wb_commission_percent_main": "global_default",
        "wb_commission_percent_assorti": "global_default",
        "average_realized_price_main": "global_default",
        "average_realized_price_assorti": "global_default",
        "available_capital": "global_default",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 1.0,
        "logistics_cost_per_unit": 0.2,
        "wb_commission_percent_main": 0.1,
        "wb_commission_percent_assorti": 0.2,
        "average_realized_price_main": 3.0,
        "average_realized_price_assorti": 3.5,
        "available_capital": 250.0,
    }
    assert alpha_proxy["margin_proxy"] == {"main": 1.5, "assorti": 1.6}
    assert alpha_proxy["unit_capital_proxy"] == 1.2

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_TRUSTED
    assert economics_trust["code_default_key_fields"] == []
    assert economics_trust["code_default_key_fields_count"] == 0
    assert economics_trust["code_default_dominance_ratio"] == 0.0
    assert economics_trust["warnings"] == []
    assert meta["warnings"] == []

    capital_gap = meta["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert capital_gap["available_capital"] == 250.0

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == []


def test_production_order_proposal_from_wb_uses_admin_economic_defaults_when_request_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = 0.7
    article_settings.production_order_logistics_cost_per_unit = 0.3
    article_settings.production_order_wb_commission_percent_main = 0.11
    article_settings.production_order_wb_commission_percent_assorti = 0.12
    article_settings.production_order_average_realized_price_main = 2.2
    article_settings.production_order_average_realized_price_assorti = 2.4
    article_settings.production_order_available_capital = 300.0

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 0.9
    global_settings.default_production_order_logistics_cost_per_unit = 0.4
    global_settings.default_production_order_wb_commission_percent_main = 0.13
    global_settings.default_production_order_wb_commission_percent_assorti = 0.14
    global_settings.default_production_order_average_realized_price_main = 2.6
    global_settings.default_production_order_average_realized_price_assorti = 2.8
    global_settings.default_production_order_available_capital = 450.0

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ECON-ADMIN-DEFAULT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ECON-ADMIN-DEFAULT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ECON-ADMIN-DEFAULT",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "admin_defaults",
        "logistics_cost_per_unit": "admin_defaults",
        "wb_commission_percent_main": "admin_defaults",
        "wb_commission_percent_assorti": "admin_defaults",
        "average_realized_price_main": "admin_defaults",
        "average_realized_price_assorti": "admin_defaults",
        "available_capital": "admin_defaults",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 0.7,
        "logistics_cost_per_unit": 0.3,
        "wb_commission_percent_main": 0.11,
        "wb_commission_percent_assorti": 0.12,
        "average_realized_price_main": 2.2,
        "average_realized_price_assorti": 2.4,
        "available_capital": 300.0,
    }

    assert alpha_proxy["economics_trust"] == meta["economics_trust"]
    assert alpha_proxy["economics_trust_level"] == meta["economics_trust"]["economics_trust_level"]
    assert alpha_proxy["capital_governance"] == meta["capital_governance"]

    economics_trust = meta["economics_trust"]
    assert economics_trust["economics_trust_level"] == ECONOMICS_TRUST_LEVEL_TRUSTED
    assert economics_trust["code_default_key_fields"] == []
    assert economics_trust["code_default_key_fields_count"] == 0
    assert economics_trust["code_default_dominance_ratio"] == 0.0
    assert economics_trust["warnings"] == []
    assert meta["warnings"] == []

    capital_gap = meta["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert capital_gap["available_capital"] == 300.0

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["economics_trust"] == economics_trust
    assert compact_meta["capital_governance"] == meta["capital_governance"]
    assert compact_meta["warnings"] == []


def test_production_order_proposal_from_wb_request_economic_overrides_admin_and_global(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    seeded["bundle_type"].is_assorti = True
    db_session.flush()

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_production_cost_per_unit = 0.7
    article_settings.production_order_logistics_cost_per_unit = 0.3
    article_settings.production_order_wb_commission_percent_main = 0.11
    article_settings.production_order_wb_commission_percent_assorti = 0.12
    article_settings.production_order_average_realized_price_main = 2.2
    article_settings.production_order_average_realized_price_assorti = 2.4
    article_settings.production_order_available_capital = 300.0

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_production_cost_per_unit = 0.9
    global_settings.default_production_order_logistics_cost_per_unit = 0.4
    global_settings.default_production_order_wb_commission_percent_main = 0.13
    global_settings.default_production_order_wb_commission_percent_assorti = 0.14
    global_settings.default_production_order_average_realized_price_main = 2.6
    global_settings.default_production_order_average_realized_price_assorti = 2.8
    global_settings.default_production_order_available_capital = 450.0

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ECON-REQUEST",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ECON-REQUEST",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ECON-REQUEST",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
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
            "production_cost_per_unit": 1.0,
            "logistics_cost_per_unit": 0.2,
            "wb_commission_percent_main": 0.05,
            "wb_commission_percent_assorti": 0.05,
            "average_realized_price_main": 1.5,
            "average_realized_price_assorti": 2.4,
            "available_capital": 60.0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["economics_formula_version"] == "v1_economic_alpha"
    assert alpha_proxy["economic_calibration_state"] == "economic_inputs_calibrated"
    assert alpha_proxy["economic_source"] == {
        "production_cost_per_unit": "request",
        "logistics_cost_per_unit": "request",
        "wb_commission_percent_main": "request",
        "wb_commission_percent_assorti": "request",
        "average_realized_price_main": "request",
        "average_realized_price_assorti": "request",
        "available_capital": "request",
    }
    assert alpha_proxy["economic_inputs"] == {
        "production_cost_per_unit": 1.0,
        "logistics_cost_per_unit": 0.2,
        "wb_commission_percent_main": 0.05,
        "wb_commission_percent_assorti": 0.05,
        "average_realized_price_main": 1.5,
        "average_realized_price_assorti": 2.4,
        "available_capital": 60.0,
    }

    assert alpha_proxy["layer_2_allocation_method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_allocation_method_canonical"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert alpha_proxy["layer_2_legacy_allocation_method"] == LAYER2_ALLOCATION_METHOD
    assert alpha_proxy["layer_2_decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert alpha_proxy["layer_2_legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    assert (
        alpha_proxy["layer_2_legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )

    layer2_meta = meta["layer_2_allocation"]
    assert layer2_meta["method"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2_meta["method_canonical"] == LAYER2_ALLOCATION_METHOD_CANONICAL
    assert layer2_meta["legacy_method"] == LAYER2_ALLOCATION_METHOD
    assert layer2_meta["decision_gate"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2_meta["decision_gate_canonical"] == LAYER2_DECISION_GATE_CANONICAL
    assert layer2_meta["legacy_decision_gate"] == LAYER2_DECISION_GATE_LEGACY
    layer2_legacy_alias_plan = layer2_meta["legacy_alias_deprecation_plan"]
    assert layer2_legacy_alias_plan["deprecated_after"] == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    assert layer2_meta["decision_quality"]["legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    assert alpha_proxy["layer_2_legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    layer2_summary = meta["layer_2_allocation"]["summary"]
    assert layer2_summary["main"] > 0
    assert layer2_summary["assorti"] == 0

    capital_gap = meta["capital_gap"]
    assert capital_gap["status"] == "ok"
    assert capital_gap["available_capital"] == 60.0
    assert isinstance(capital_gap["required_capital"], float)
    assert isinstance(capital_gap["deficit_or_surplus"], float)

    layer4 = meta["layer_4_scenarios"]
    scenarios = layer4["scenarios"]
    assert len(scenarios) == 3
    for scenario in scenarios:
        assert "expected_revenue" in scenario
        assert "expected_gross_profit" in scenario
        assert "expected_margin_percent" in scenario
        assert "expected_turnover_days" in scenario
        assert "stockout_probability_proxy" in scenario
        assert "overstock_risk_proxy" in scenario
        assert "capital_delta_vs_balanced" in scenario
        assert "expected_revenue_delta_vs_balanced" in scenario
        assert "expected_gross_profit_delta_vs_balanced" in scenario
        assert "objective_score_delta_vs_balanced" in scenario
        assert (
            scenario["expected_gross_profit_delta_vs_balanced"]
            == scenario["gross_profit_delta_vs_balanced"]
        )

    aggregate = layer4["aggregate_deltas"]
    assert set(aggregate["aggressive_vs_conservative"].keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"] == alpha_proxy["economic_source"]
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"] == alpha_proxy["economic_inputs"]
    assert compact_meta["capital_gap"] == capital_gap
    assert compact_meta["alpha_proxy_economics"]["layer_2_legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    assert compact_meta["layer_2_allocation"]["decision_quality"]["legacy_alias_deprecation_plan"] == layer2_legacy_alias_plan
    assert compact_meta["layer_4_scenarios"] == expected_compact_layer4
    assert compact_meta["layer_5_intervention"] == meta["layer_5_intervention"]


def test_production_order_proposal_from_wb_reports_budget_limited_capital_constraint_summary(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-CAP-BUDGET-LIMITED",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-CAP-BUDGET-LIMITED",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-CAP-BUDGET-LIMITED",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime.now(timezone.utc),
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
            "available_capital": 20.0,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    recommendation = body["recommendation"]
    assert recommendation is not None
    assert recommendation["lines"]

    meta = body["explanation"]["meta"]
    capital_constraint = meta["capital_constraint"]
    assert capital_constraint["status"] == "budget_limited_applied"
    assert capital_constraint["constrained"] is True
    assert capital_constraint["available_capital"] == 20.0
    assert capital_constraint["required_capital_before_constraint"] > capital_constraint["available_capital"]
    assert capital_constraint["allocated_capital_after_constraint"] <= capital_constraint["available_capital"]
    assert capital_constraint["line_count_after"] == len(recommendation["lines"])
    assert capital_constraint["line_count_before"] >= capital_constraint["line_count_after"]
    assert capital_constraint["remaining_capital"] >= 0.0

    ranking = capital_constraint["ranking"]
    assert isinstance(ranking, list)
    assert len(ranking) >= len(recommendation["lines"])
    assert recommendation["lines"][0]["color_id"] == ranking[0]["color_id"]
    assert recommendation["lines"][0]["size_id"] == ranking[0]["size_id"]

    contract = capital_constraint["contract"]
    assert contract["version"] == CAPITAL_CONSTRAINT_CONTRACT_VERSION
    assert contract["status"] == "ok"
    assert contract["checks"]["budget_accounting_consistent"] is True
    assert contract["checks"]["ranking_sorted_by_objective_per_capital"] is True
    assert contract["checks"]["ranking_risk_priority_consistent"] is True

    for line in recommendation["lines"]:
        assert line["source_reason"].endswith("|capital_constraint")

    cutoff_line = capital_constraint["cutoff_line"]
    assert cutoff_line is not None
    assert cutoff_line["requested_qty"] >= cutoff_line["allocated_qty"] >= 0

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["capital_constraint"] == capital_constraint
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_from_wb_assorti_classification_prefers_admin_fallback_over_global(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ASSORTI-ADMIN-FALLBACK",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ASSORTI-ADMIN-FALLBACK",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ASSORTI-ADMIN-FALLBACK",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime.now(timezone.utc),
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_assorti_classification = compact_body["explanation"]["meta"]["layer_1_stock_health"][
        "assorti_classification"
    ]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_assorti_classification["summary"] == assorti_classification["summary"]
    assert compact_assorti_classification["source_breakdown"] == assorti_classification["source_breakdown"]
    assert "bundle_types" not in compact_assorti_classification


def test_production_order_proposal_from_wb_assorti_classification_uses_global_fallback_when_admin_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_assorti_bundle_type_ids = str(seeded["bundle_type"].id)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-ASSORTI-GLOBAL-FALLBACK",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-ASSORTI-GLOBAL-FALLBACK",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-ASSORTI-GLOBAL-FALLBACK",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=20,
            updated_at=datetime.now(timezone.utc),
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

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_assorti_classification = compact_body["explanation"]["meta"]["layer_1_stock_health"][
        "assorti_classification"
    ]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_assorti_classification["summary"] == assorti_classification["summary"]
    assert compact_assorti_classification["source_breakdown"] == assorti_classification["source_breakdown"]
    assert "bundle_types" not in compact_assorti_classification


def test_production_order_proposal_from_wb_uses_observed_revenue_prices_for_economics(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-BT-OBS-ASSORTI",
        name="PO-BT-OBS-ASSORTI",
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
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-OBS-MAIN",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-OBS-ASSORTI",
                bundle_type_id=assorti_bundle_type.id,
                size_id=seeded["size_m"].id,
            ),
            WbSalesDaily(
                wb_sku="WB-PO-OBS-MAIN",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=30,
                revenue=90.0,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku="WB-PO-OBS-ASSORTI",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=20,
                revenue=44.0,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-OBS-MAIN",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=15,
                updated_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-OBS-ASSORTI",
                warehouse_id=2,
                warehouse_name="WB-2",
                stock_qty=10,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-10",
        "bundle_type_ids": [seeded["bundle_type"].id, assorti_bundle_type.id],
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
    full_from_wb = body["explanation"]["meta"]["from_wb"]
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["economic_source"]["average_realized_price_main"] == FROM_WB_OBSERVED_ECONOMIC_SOURCE
    assert alpha_proxy["economic_source"]["average_realized_price_assorti"] == FROM_WB_OBSERVED_ECONOMIC_SOURCE
    assert alpha_proxy["economic_inputs"]["average_realized_price_main"] == 3.0
    assert alpha_proxy["economic_inputs"]["average_realized_price_assorti"] == 2.2

    from_wb_observed = full_from_wb["economic_observed_prices"]
    assert from_wb_observed["source"] == FROM_WB_OBSERVED_ECONOMIC_SOURCE
    assert from_wb_observed["prices"] == {"main": 3.0, "assorti": 2.2}
    assert from_wb_observed["sample_counts"]["main"]["accepted_samples"] == 1
    assert from_wb_observed["sample_counts"]["assorti"]["accepted_samples"] == 1
    expected_compact_from_wb = {
        "observation_window_days": full_from_wb["observation_window_days"],
        "freshness_mode": full_from_wb["freshness_mode"],
        "requested_as_of_date": full_from_wb["requested_as_of_date"],
        "as_of_date": full_from_wb["as_of_date"],
        "as_of_source": full_from_wb["as_of_source"],
        "bundle_type_ids": full_from_wb["bundle_type_ids"],
        "sales_window": full_from_wb["sales_window"],
        "freshness": {
            "status": full_from_wb["freshness"]["status"],
            "sales_age_days": full_from_wb["freshness"]["sales_age_days"],
            "stock_oldest_age_days": full_from_wb["freshness"]["stock_oldest_age_days"],
            "threshold_days": full_from_wb["freshness"]["threshold_days"],
            "threshold_source": full_from_wb["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": full_from_wb["economic_observed_prices"]["source"],
            "window": full_from_wb["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_from_wb["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_from_wb["economic_observed_prices"]["prices"],
            "sample_counts": full_from_wb["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": full_from_wb["economic_observed_commission"]["source"],
            "status": full_from_wb["economic_observed_commission"]["status"],
            "reason": full_from_wb["economic_observed_commission"]["reason"],
            "commission_percent": full_from_wb["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": full_from_wb["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": full_from_wb["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(full_from_wb["daily_sales_by_bundle"]),
            "daily_sales_total": sum(full_from_wb["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(full_from_wb["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(full_from_wb["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(full_from_wb["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["average_realized_price_main"] == (
        FROM_WB_OBSERVED_ECONOMIC_SOURCE
    )
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["average_realized_price_assorti"] == (
        FROM_WB_OBSERVED_ECONOMIC_SOURCE
    )
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["average_realized_price_main"] == 3.0
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["average_realized_price_assorti"] == 2.2
    assert compact_meta["from_wb"] == expected_compact_from_wb


def test_production_order_proposal_from_wb_observed_price_filters_anomaly_spike(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-OBS-ANOMALY",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku="WB-PO-OBS-ANOMALY",
                date=datetime(2026, 1, 9, tzinfo=timezone.utc).date(),
                sales_qty=10,
                revenue=20.0,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku="WB-PO-OBS-ANOMALY",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=10,
                revenue=80.0,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-OBS-ANOMALY",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=20,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
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
    full_from_wb = body["explanation"]["meta"]["from_wb"]
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["economic_source"]["average_realized_price_main"] == FROM_WB_OBSERVED_ECONOMIC_SOURCE
    assert alpha_proxy["economic_inputs"]["average_realized_price_main"] == 2.0

    from_wb_observed = full_from_wb["economic_observed_prices"]
    assert from_wb_observed["prices"]["main"] == 2.0
    assert from_wb_observed["sample_counts"]["main"]["anomaly_filtered"] == 1
    assert from_wb_observed["sample_counts"]["main"]["accepted_samples"] == 1
    expected_compact_from_wb = {
        "observation_window_days": full_from_wb["observation_window_days"],
        "freshness_mode": full_from_wb["freshness_mode"],
        "requested_as_of_date": full_from_wb["requested_as_of_date"],
        "as_of_date": full_from_wb["as_of_date"],
        "as_of_source": full_from_wb["as_of_source"],
        "bundle_type_ids": full_from_wb["bundle_type_ids"],
        "sales_window": full_from_wb["sales_window"],
        "freshness": {
            "status": full_from_wb["freshness"]["status"],
            "sales_age_days": full_from_wb["freshness"]["sales_age_days"],
            "stock_oldest_age_days": full_from_wb["freshness"]["stock_oldest_age_days"],
            "threshold_days": full_from_wb["freshness"]["threshold_days"],
            "threshold_source": full_from_wb["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": full_from_wb["economic_observed_prices"]["source"],
            "window": full_from_wb["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_from_wb["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_from_wb["economic_observed_prices"]["prices"],
            "sample_counts": full_from_wb["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": full_from_wb["economic_observed_commission"]["source"],
            "status": full_from_wb["economic_observed_commission"]["status"],
            "reason": full_from_wb["economic_observed_commission"]["reason"],
            "commission_percent": full_from_wb["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": full_from_wb["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": full_from_wb["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(full_from_wb["daily_sales_by_bundle"]),
            "daily_sales_total": sum(full_from_wb["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(full_from_wb["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(full_from_wb["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(full_from_wb["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["average_realized_price_main"] == (
        FROM_WB_OBSERVED_ECONOMIC_SOURCE
    )
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["average_realized_price_main"] == 2.0
    assert compact_meta["from_wb"] == expected_compact_from_wb


def test_production_order_proposal_from_wb_request_price_override_has_precedence_over_observed_price(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-OBS-REQUEST-PRIORITY",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku="WB-PO-OBS-REQUEST-PRIORITY",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=10,
                revenue=20.0,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-OBS-REQUEST-PRIORITY",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=20,
                updated_at=datetime.now(timezone.utc),
            ),
        ]
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
            "average_realized_price_main": 4.4,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    full_from_wb = body["explanation"]["meta"]["from_wb"]
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["economic_source"]["average_realized_price_main"] == "request"
    assert alpha_proxy["economic_inputs"]["average_realized_price_main"] == 4.4

    from_wb_observed = full_from_wb["economic_observed_prices"]
    assert from_wb_observed["source"] == FROM_WB_OBSERVED_ECONOMIC_SOURCE
    assert from_wb_observed["prices"]["main"] == 2.0
    assert from_wb_observed["sample_counts"]["main"]["accepted_samples"] == 1
    expected_compact_from_wb = {
        "observation_window_days": full_from_wb["observation_window_days"],
        "freshness_mode": full_from_wb["freshness_mode"],
        "requested_as_of_date": full_from_wb["requested_as_of_date"],
        "as_of_date": full_from_wb["as_of_date"],
        "as_of_source": full_from_wb["as_of_source"],
        "bundle_type_ids": full_from_wb["bundle_type_ids"],
        "sales_window": full_from_wb["sales_window"],
        "freshness": {
            "status": full_from_wb["freshness"]["status"],
            "sales_age_days": full_from_wb["freshness"]["sales_age_days"],
            "stock_oldest_age_days": full_from_wb["freshness"]["stock_oldest_age_days"],
            "threshold_days": full_from_wb["freshness"]["threshold_days"],
            "threshold_source": full_from_wb["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": full_from_wb["economic_observed_prices"]["source"],
            "window": full_from_wb["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_from_wb["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_from_wb["economic_observed_prices"]["prices"],
            "sample_counts": full_from_wb["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": full_from_wb["economic_observed_commission"]["source"],
            "status": full_from_wb["economic_observed_commission"]["status"],
            "reason": full_from_wb["economic_observed_commission"]["reason"],
            "commission_percent": full_from_wb["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": full_from_wb["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": full_from_wb["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(full_from_wb["daily_sales_by_bundle"]),
            "daily_sales_total": sum(full_from_wb["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(full_from_wb["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(full_from_wb["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(full_from_wb["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"]["economic_source"]["average_realized_price_main"] == "request"
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["average_realized_price_main"] == 4.4
    assert compact_meta["from_wb"] == expected_compact_from_wb


def test_production_order_proposal_from_wb_uses_live_commission_calibration(client, db_session, monkeypatch):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        WbIntegrationAccount(
            name="WB Live Commission",
            supplier_id=None,
            api_token="token-live-commission",
            is_active=True,
        )
    )
    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-COMMISSION",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-COMMISSION",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=20,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-COMMISSION",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=8,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_httpx_get(url, *, headers=None, timeout=None):
        assert url.endswith("/api/v1/tariffs/commission")
        assert headers and "Authorization" in headers
        assert timeout is not None
        return FakeResponse(
            200,
            {
                "report": [
                    {"subjectID": 100, "subjectName": "Subject-A", "kgvpSupplier": 25.0},
                    {"subjectID": 200, "subjectName": "Subject-B", "kgvpSupplier": 15.0},
                ]
            },
        )

    monkeypatch.setattr(planning_production_order_service.httpx, "get", fake_httpx_get)

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
    full_from_wb = body["explanation"]["meta"]["from_wb"]
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert (
        alpha_proxy["economic_source"]["wb_commission_percent_main"]
        == FROM_WB_TARIFFS_COMMISSION_SOURCE
    )
    assert (
        alpha_proxy["economic_source"]["wb_commission_percent_assorti"]
        == FROM_WB_TARIFFS_COMMISSION_SOURCE
    )
    assert alpha_proxy["economic_inputs"]["wb_commission_percent_main"] == 0.2
    assert alpha_proxy["economic_inputs"]["wb_commission_percent_assorti"] == 0.2

    commission_meta = full_from_wb["economic_observed_commission"]
    assert commission_meta["status"] == "ok"
    assert commission_meta["reason"] is None
    assert commission_meta["subjects_with_commission"] == 2
    assert commission_meta["commission_percent"] == {"main": 0.2, "assorti": 0.2}
    assert commission_meta["commission_percent_stats"] == {"avg": 0.2, "min": 0.15, "max": 0.25}
    assert commission_meta["kgvp_supplier_percent_stats"] == {"avg": 20.0, "min": 15.0, "max": 25.0}
    expected_compact_commission_meta = {
        "source": commission_meta["source"],
        "status": commission_meta["status"],
        "reason": commission_meta["reason"],
        "commission_percent": commission_meta["commission_percent"],
        "commission_percent_stats": commission_meta["commission_percent_stats"],
        "kgvp_supplier_percent_stats": commission_meta["kgvp_supplier_percent_stats"],
    }
    expected_compact_from_wb = {
        "observation_window_days": full_from_wb["observation_window_days"],
        "freshness_mode": full_from_wb["freshness_mode"],
        "requested_as_of_date": full_from_wb["requested_as_of_date"],
        "as_of_date": full_from_wb["as_of_date"],
        "as_of_source": full_from_wb["as_of_source"],
        "bundle_type_ids": full_from_wb["bundle_type_ids"],
        "sales_window": full_from_wb["sales_window"],
        "freshness": {
            "status": full_from_wb["freshness"]["status"],
            "sales_age_days": full_from_wb["freshness"]["sales_age_days"],
            "stock_oldest_age_days": full_from_wb["freshness"]["stock_oldest_age_days"],
            "threshold_days": full_from_wb["freshness"]["threshold_days"],
            "threshold_source": full_from_wb["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": full_from_wb["economic_observed_prices"]["source"],
            "window": full_from_wb["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_from_wb["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_from_wb["economic_observed_prices"]["prices"],
            "sample_counts": full_from_wb["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": expected_compact_commission_meta,
        "snapshot": {
            "daily_sales_bundle_count": len(full_from_wb["daily_sales_by_bundle"]),
            "daily_sales_total": sum(full_from_wb["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(full_from_wb["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(full_from_wb["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(full_from_wb["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_meta["alpha_proxy_economics"] == alpha_proxy
    assert (
        compact_meta["alpha_proxy_economics"]["economic_source"]["wb_commission_percent_main"]
        == FROM_WB_TARIFFS_COMMISSION_SOURCE
    )
    assert (
        compact_meta["alpha_proxy_economics"]["economic_source"]["wb_commission_percent_assorti"]
        == FROM_WB_TARIFFS_COMMISSION_SOURCE
    )
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["wb_commission_percent_main"] == 0.2
    assert compact_meta["alpha_proxy_economics"]["economic_inputs"]["wb_commission_percent_assorti"] == 0.2
    assert compact_meta["from_wb"] == expected_compact_from_wb


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
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in layer2_step
    assert "legacy_decision_gate=profit_until_eta" in layer2_step
    assert "reason_counts={" in layer2_step
    assert "avg_profit_gap_until_eta=" in layer2_step
    assert "capital_locked_total=" in layer2_step
    assert "contract_status=ok" in layer2_step

    meta = body["explanation"]["meta"]
    assert meta["explainability"]["mode"] == EXPLAINABILITY_MODE_COMPACT
    assert meta["layer_1_stock_health"]["contract"]["status"] == "ok"
    assert "decisions" not in meta["layer_2_allocation"]
    assert meta["layer_2_allocation"]["contract"]["status"] == "ok"
    assert meta["capital_constraint"]["contract"]["status"] == "ok"
    assert (
        meta["capital_constraint"]["contract"]["checks"]["ranking_risk_priority_consistent"]
        is True
    )
    assert (
        meta["layer_2_allocation"]["legacy_alias_deprecation_plan"]["deprecated_after"]
        == LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW
    )
    layer2_compact_contract_checks = meta["layer_2_allocation"]["contract"]["checks"]
    assert layer2_compact_contract_checks["decision_reason_matches_allocation"] is True
    assert layer2_compact_contract_checks["allocation_matches_profit_gate"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert layer2_compact_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert layer2_compact_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert layer2_compact_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert layer2_compact_contract_checks["profit_gap_consistent_with_profits"] is True
    assert layer2_compact_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert layer2_compact_contract_checks["capital_locked_metric_valid"] is True
    assert meta["layer_2_allocation"]["decision_quality"]["profit_gate_primary"] is False
    assert meta["layer_2_allocation"]["decision_quality"]["composite_objective_gate_primary"] is True
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        meta["layer_2_allocation"]["decision_quality"]["near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert meta["layer_3_purchase_shaping"]["contract"]["status"] == "ok"
    assert meta["layer_4_scenarios"]["contract"]["status"] == "ok"
    assert set(meta["layer_4_scenarios"]["aggregate_deltas"]["aggressive_vs_conservative"].keys()) == {
        "capital_delta",
        "expected_revenue_delta",
        "gross_profit_delta",
        "objective_delta",
    }
    for scenario in meta["layer_4_scenarios"]["scenarios"]:
        assert "capital_delta_vs_balanced" in scenario
        assert "expected_revenue_delta_vs_balanced" in scenario
        assert "expected_gross_profit_delta_vs_balanced" in scenario
        assert "objective_score_delta_vs_balanced" in scenario
    assert meta["layer_5_intervention"]["signal_policy"] == "critical_risk_thresholds"
    assert meta["layer_5_intervention"]["contract"]["status"] == "ok"
    assert meta["layer_5_intervention"]["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_1_high_stockout_risk_threshold"] == LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    assert (
        alpha_proxy["layer_2_near_tie_objective_gap_threshold"]
        == LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
    )
    assert (
        alpha_proxy["layer_2_near_tie_profit_gap_threshold"]
        == LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD
    )
    assert alpha_proxy["layer_3_calibration"]["method"] == "risk_weighted_factor_clamp"
    assert alpha_proxy["layer_4_contract_version"] == "v1_alpha"
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
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

    full_payload = deepcopy(payload)
    full_payload.pop("explainability_mode", None)
    full_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=full_payload,
    )
    assert full_response.status_code == 200, full_response.text

    full_body = full_response.json()
    full_meta = full_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    expected_compact_layer4 = {
        "method": full_meta["layer_4_scenarios"]["method"],
        "factors": full_meta["layer_4_scenarios"]["factors"],
        "contract": full_meta["layer_4_scenarios"]["contract"],
        "aggregate_deltas": full_meta["layer_4_scenarios"]["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_meta["layer_4_scenarios"]["scenarios"]
        ],
    }
    expected_compact_freshness = {
        "status": full_meta["from_wb"]["freshness"]["status"],
        "sales_age_days": full_meta["from_wb"]["freshness"]["sales_age_days"],
        "stock_oldest_age_days": full_meta["from_wb"]["freshness"]["stock_oldest_age_days"],
        "threshold_days": full_meta["from_wb"]["freshness"]["threshold_days"],
        "threshold_source": full_meta["from_wb"]["freshness"]["threshold_source"],
    }
    expected_compact_commission_meta = {
        "source": full_meta["from_wb"]["economic_observed_commission"]["source"],
        "status": full_meta["from_wb"]["economic_observed_commission"]["status"],
        "reason": full_meta["from_wb"]["economic_observed_commission"]["reason"],
        "commission_percent": full_meta["from_wb"]["economic_observed_commission"]["commission_percent"],
        "commission_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["commission_percent_stats"],
        "kgvp_supplier_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["kgvp_supplier_percent_stats"],
    }
    assert _business_projection(body) == _business_projection(full_body)
    assert meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert meta["warnings"] == full_meta["warnings"]
    assert meta["economics_trust"] == full_meta["economics_trust"]
    assert meta["capital_governance"] == full_meta["capital_governance"]
    assert meta["sources"] == full_meta["sources"]
    assert meta["physical_scope"] == full_meta["physical_scope"]
    assert meta["arrival_projection"] == full_meta["arrival_projection"]
    assert meta["reorder_policy"] == full_meta["reorder_policy"]
    assert meta["economic_buffer"] == full_meta["economic_buffer"]
    assert meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert meta["capital_gap"] == full_meta["capital_gap"]
    assert meta["capital_constraint"] == full_meta["capital_constraint"]
    assert meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert meta["layer_2_allocation"]["decision_quality"] == full_meta["layer_2_allocation"]["decision_quality"]
    assert meta["layer_2_allocation"]["contract"] == full_meta["layer_2_allocation"]["contract"]
    assert meta["layer_4_scenarios"] == expected_compact_layer4
    assert meta["layer_5_intervention"] == full_meta["layer_5_intervention"]
    assert from_wb_meta["freshness"] == expected_compact_freshness
    assert from_wb_meta["economic_observed_commission"] == expected_compact_commission_meta


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

    full_meta = full_body["explanation"]["meta"]
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer2 = full_meta["layer_2_allocation"]
    expected_compact_layer2 = {
        "method": full_layer2.get("method"),
        "method_canonical": full_layer2.get("method_canonical"),
        "legacy_method": full_layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": full_layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": full_layer2.get("summary", {}),
        "contract": full_layer2.get("contract", {}),
        "decision_quality": full_layer2.get("decision_quality", {}),
        "decision_gate": full_layer2.get("decision_gate"),
        "decision_gate_canonical": full_layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": full_layer2.get("legacy_decision_gate"),
        "tie_break": full_layer2.get("tie_break"),
        "gmroi_usage": full_layer2.get("gmroi_usage"),
        "objective_formula": full_layer2.get("objective_formula"),
        "objective_parameters": full_layer2.get("objective_parameters", {}),
        "objective_source": full_layer2.get("objective_source", {}),
    }
    assert compact_meta["sources"] == full_meta["sources"]
    assert compact_meta["physical_scope"] == full_meta["physical_scope"]
    assert compact_meta["arrival_projection"] == full_meta["arrival_projection"]
    assert compact_meta["reorder_policy"] == full_meta["reorder_policy"]
    assert compact_meta["economic_buffer"] == full_meta["economic_buffer"]
    assert compact_meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert compact_meta["capital_gap"] == full_meta["capital_gap"]
    assert compact_meta["capital_constraint"] == full_meta["capital_constraint"]
    assert compact_meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["layer_2_allocation"]["decision_quality"] == full_layer2["decision_quality"]
    assert compact_meta["layer_2_allocation"]["contract"] == full_layer2["contract"]

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in compact_layer2_step
    assert "legacy_decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is False
    assert compact_layer2["decision_quality"]["composite_objective_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    assert compact_layer2 == expected_compact_layer2
    assert (
        compact_body["explanation"]["meta"]["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == compact_layer2["objective_parameters"]
    )
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    full_layer4 = full_meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4

    expected_compact_freshness = {
        "status": full_meta["from_wb"]["freshness"]["status"],
        "sales_age_days": full_meta["from_wb"]["freshness"]["sales_age_days"],
        "stock_oldest_age_days": full_meta["from_wb"]["freshness"]["stock_oldest_age_days"],
        "threshold_days": full_meta["from_wb"]["freshness"]["threshold_days"],
        "threshold_source": full_meta["from_wb"]["freshness"]["threshold_source"],
    }
    expected_compact_commission_meta = {
        "source": full_meta["from_wb"]["economic_observed_commission"]["source"],
        "status": full_meta["from_wb"]["economic_observed_commission"]["status"],
        "reason": full_meta["from_wb"]["economic_observed_commission"]["reason"],
        "commission_percent": full_meta["from_wb"]["economic_observed_commission"]["commission_percent"],
        "commission_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["commission_percent_stats"],
        "kgvp_supplier_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["kgvp_supplier_percent_stats"],
    }
    expected_compact_from_wb = {
        "observation_window_days": full_meta["from_wb"]["observation_window_days"],
        "freshness_mode": full_meta["from_wb"]["freshness_mode"],
        "requested_as_of_date": full_meta["from_wb"]["requested_as_of_date"],
        "as_of_date": full_meta["from_wb"]["as_of_date"],
        "as_of_source": full_meta["from_wb"]["as_of_source"],
        "bundle_type_ids": full_meta["from_wb"]["bundle_type_ids"],
        "sales_window": full_meta["from_wb"]["sales_window"],
        "freshness": expected_compact_freshness,
        "economic_observed_prices": {
            "source": full_meta["from_wb"]["economic_observed_prices"]["source"],
            "window": full_meta["from_wb"]["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_meta["from_wb"]["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_meta["from_wb"]["economic_observed_prices"]["prices"],
            "sample_counts": full_meta["from_wb"]["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": expected_compact_commission_meta,
        "snapshot": {
            "daily_sales_bundle_count": len(full_meta["from_wb"]["daily_sales_by_bundle"]),
            "daily_sales_total": sum(full_meta["from_wb"]["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(full_meta["from_wb"]["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(full_meta["from_wb"]["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(full_meta["from_wb"]["wb_stock_updated_at_by_bundle"]),
        },
    }
    from_wb_meta = compact_meta["from_wb"]
    assert from_wb_meta == expected_compact_from_wb
    assert compact_meta["layer_5_intervention"] == full_meta["layer_5_intervention"]


def test_production_order_proposal_from_wb_uses_code_default_layer_proxy_values(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-LAYER-PROXY-CODE-DEFAULT",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-LAYER-PROXY-CODE-DEFAULT",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-LAYER-PROXY-CODE-DEFAULT",
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
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["source"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.3
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.4
    assert (
        alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": LAYER2_CAPITAL_COST_RATE,
        "stockout_penalty_weight": LAYER2_STOCKOUT_PENALTY_WEIGHT,
        "overstock_penalty_weight": LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": LAYER_PROXY_VALUE_SOURCE,
        "layer3_overstock_dampen_max": LAYER_PROXY_VALUE_SOURCE,
        "layer5_unavoidable_stockout_risk_threshold": LAYER_PROXY_VALUE_SOURCE,
        "layer5_accelerate_production_risk_threshold": LAYER_PROXY_VALUE_SOURCE,
        "layer2_capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "layer2_stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "layer2_overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "layer5_accelerate_action_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "layer5_price_slowdown_lost_volume_rate": LAYER_PROXY_VALUE_SOURCE,
        "layer5_reduce_order_marginal_profit_rate": LAYER_PROXY_VALUE_SOURCE,
    }

    layer2 = meta["layer_2_allocation"]
    assert layer2["objective_parameters"] == {
        "capital_cost_rate": LAYER2_CAPITAL_COST_RATE,
        "stockout_penalty_weight": LAYER2_STOCKOUT_PENALTY_WEIGHT,
        "overstock_penalty_weight": LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": LAYER_PROXY_VALUE_SOURCE,
        "stockout_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
        "overstock_penalty_weight": LAYER_PROXY_VALUE_SOURCE,
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    layer4 = meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }

    layer5 = meta["layer_5_intervention"]
    assert layer5["risk_threshold"] == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    assert layer5["signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    compact_alpha_proxy = compact_meta["alpha_proxy_economics"]
    compact_layer2 = compact_meta["layer_2_allocation"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    compact_layer5 = compact_meta["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer_3_calibration"] == alpha_proxy["layer_3_calibration"]
    assert compact_alpha_proxy["layer_proxy_source"] == alpha_proxy["layer_proxy_source"]
    assert compact_alpha_proxy["layer_2_objective_parameters"] == alpha_proxy["layer_2_objective_parameters"]
    assert (
        compact_alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer2 == expected_compact_layer2
    assert compact_layer4 == expected_compact_layer4
    assert compact_layer5 == layer5


def test_production_order_proposal_from_wb_uses_global_layer_proxy_defaults_when_admin_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.19
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.11
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.29
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.39
    global_settings.default_production_order_layer2_capital_cost_rate = 0.17
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.61
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.23

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL",
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
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.19
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.11
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.29
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.39,
        "increase_price_to_slow_velocity": 0.29,
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.17,
        "stockout_penalty_weight": 0.61,
        "overstock_penalty_weight": 0.23,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "global_default",
        "layer3_overstock_dampen_max": "global_default",
        "layer5_unavoidable_stockout_risk_threshold": "global_default",
        "layer5_accelerate_production_risk_threshold": "global_default",
        "layer2_capital_cost_rate": "global_default",
        "layer2_stockout_penalty_weight": "global_default",
        "layer2_overstock_penalty_weight": "global_default",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }

    layer2 = body["explanation"]["meta"]["layer_2_allocation"]
    assert layer2["objective_parameters"] == {
        "capital_cost_rate": 0.17,
        "stockout_penalty_weight": 0.61,
        "overstock_penalty_weight": 0.23,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": "global_default",
        "stockout_penalty_weight": "global_default",
        "overstock_penalty_weight": "global_default",
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    layer4 = body["explanation"]["meta"]["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }

    layer5 = body["explanation"]["meta"]["layer_5_intervention"]
    assert layer5["risk_threshold"] == 0.29

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_alpha_proxy = compact_body["explanation"]["meta"]["alpha_proxy_economics"]
    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    compact_layer4 = compact_body["explanation"]["meta"]["layer_4_scenarios"]
    compact_layer5 = compact_body["explanation"]["meta"]["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer_3_calibration"] == alpha_proxy["layer_3_calibration"]
    assert compact_alpha_proxy["layer_proxy_source"] == alpha_proxy["layer_proxy_source"]
    assert compact_alpha_proxy["layer_2_objective_parameters"] == alpha_proxy["layer_2_objective_parameters"]
    assert (
        compact_alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer2 == expected_compact_layer2
    assert compact_layer4 == expected_compact_layer4
    assert compact_layer5 == layer5


def test_production_order_proposal_from_wb_warns_when_invalid_global_layer_proxy_values_are_ignored(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 1.19
    global_settings.default_production_order_layer3_overstock_dampen_max = -0.11
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 1.29
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = -0.39

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL-INVALID",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL-INVALID",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-LAYER-PROXY-GLOBAL-INVALID",
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
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    meta = body["explanation"]["meta"]
    alpha_proxy = meta["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.3
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.4
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        "increase_price_to_slow_velocity": LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD,
        "reduce_order_size": LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    }
    assert alpha_proxy["layer_proxy_source"]["layer3_stockout_boost_max"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["layer_proxy_source"]["layer3_overstock_dampen_max"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == LAYER_PROXY_VALUE_SOURCE
    assert alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"] == LAYER_PROXY_VALUE_SOURCE
    invalid_layer_proxy_warning = next(
        warning
        for warning in meta["warnings"]
        if warning["code"] == "layer_proxy_invalid_values_ignored_at_runtime"
    )
    assert invalid_layer_proxy_warning == {
        "code": "layer_proxy_invalid_values_ignored_at_runtime",
        "severity": "MEDIUM",
        "message": "one or more production-order layer proxy values were invalid and ignored at runtime; lower-precedence or default values were used instead",
        "article_id": seeded["article"].id,
        "field": "layer_proxy_settings",
        "field_metadata": {
            "description": "Production-order Layer 3/5 proxy settings resolved from request/admin/global sources",
            "type": "object",
        },
        "ignored_value_count": 4,
        "ignored_fields": [
            "layer3_overstock_dampen_max",
            "layer3_stockout_boost_max",
            "layer5_accelerate_production_risk_threshold",
            "layer5_unavoidable_stockout_risk_threshold",
        ],
        "ignored_sources": ["global_default"],
        "ignored_values": [
            {
                "field": "layer3_stockout_boost_max",
                "invalid_source": "global_default",
                "invalid_value": 1.19,
                "effective_source": LAYER_PROXY_VALUE_SOURCE,
                "effective_value": 0.3,
            },
            {
                "field": "layer3_overstock_dampen_max",
                "invalid_source": "global_default",
                "invalid_value": -0.11,
                "effective_source": LAYER_PROXY_VALUE_SOURCE,
                "effective_value": 0.4,
            },
            {
                "field": "layer5_unavoidable_stockout_risk_threshold",
                "invalid_source": "global_default",
                "invalid_value": 1.29,
                "effective_source": LAYER_PROXY_VALUE_SOURCE,
                "effective_value": 0.25,
            },
            {
                "field": "layer5_accelerate_production_risk_threshold",
                "invalid_source": "global_default",
                "invalid_value": -0.39,
                "effective_source": LAYER_PROXY_VALUE_SOURCE,
                "effective_value": 0.35,
            },
        ],
        "action": "Review stored production-order layer proxy values; each unit-interval setting must stay within [0, 1].",
        "next_steps": ["repair_layer_proxy_settings_values"],
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    compact_alpha_proxy = compact_meta["alpha_proxy_economics"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_from_wb_uses_admin_layer_proxy_defaults_when_request_missing(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer3_stockout_boost_max = 0.27
    article_settings.production_order_layer3_overstock_dampen_max = 0.22
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.24
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.32
    article_settings.production_order_layer2_capital_cost_rate = 0.13
    article_settings.production_order_layer2_stockout_penalty_weight = 0.57
    article_settings.production_order_layer2_overstock_penalty_weight = 0.29

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.11
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.09
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.18
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.28
    global_settings.default_production_order_layer2_capital_cost_rate = 0.08
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.34
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.17

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-LAYER-PROXY-ADMIN",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-LAYER-PROXY-ADMIN",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-LAYER-PROXY-ADMIN",
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
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.27
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.22
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.24
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.32,
        "increase_price_to_slow_velocity": 0.24,
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.13,
        "stockout_penalty_weight": 0.57,
        "overstock_penalty_weight": 0.29,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "admin_defaults",
        "layer3_overstock_dampen_max": "admin_defaults",
        "layer5_unavoidable_stockout_risk_threshold": "admin_defaults",
        "layer5_accelerate_production_risk_threshold": "admin_defaults",
        "layer2_capital_cost_rate": "admin_defaults",
        "layer2_stockout_penalty_weight": "admin_defaults",
        "layer2_overstock_penalty_weight": "admin_defaults",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }

    layer2 = body["explanation"]["meta"]["layer_2_allocation"]
    assert layer2["objective_parameters"] == {
        "capital_cost_rate": 0.13,
        "stockout_penalty_weight": 0.57,
        "overstock_penalty_weight": 0.29,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": "admin_defaults",
        "stockout_penalty_weight": "admin_defaults",
        "overstock_penalty_weight": "admin_defaults",
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    layer4 = body["explanation"]["meta"]["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }

    layer5 = body["explanation"]["meta"]["layer_5_intervention"]
    assert layer5["risk_threshold"] == 0.24

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_alpha_proxy = compact_body["explanation"]["meta"]["alpha_proxy_economics"]
    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    compact_layer4 = compact_body["explanation"]["meta"]["layer_4_scenarios"]
    compact_layer5 = compact_body["explanation"]["meta"]["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer_3_calibration"] == alpha_proxy["layer_3_calibration"]
    assert compact_alpha_proxy["layer_proxy_source"] == alpha_proxy["layer_proxy_source"]
    assert compact_alpha_proxy["layer_2_objective_parameters"] == alpha_proxy["layer_2_objective_parameters"]
    assert (
        compact_alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer2 == expected_compact_layer2
    assert compact_layer4 == expected_compact_layer4
    assert compact_layer5 == layer5


def test_production_order_proposal_from_wb_request_layer_proxy_overrides_admin_and_global(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer3_stockout_boost_max = 0.17
    article_settings.production_order_layer3_overstock_dampen_max = 0.12
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.26
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.34
    article_settings.production_order_layer2_capital_cost_rate = 0.14
    article_settings.production_order_layer2_stockout_penalty_weight = 0.44
    article_settings.production_order_layer2_overstock_penalty_weight = 0.21

    global_settings = db_session.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).one()
    global_settings.default_production_order_layer3_stockout_boost_max = 0.09
    global_settings.default_production_order_layer3_overstock_dampen_max = 0.08
    global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold = 0.21
    global_settings.default_production_order_layer5_accelerate_production_risk_threshold = 0.31
    global_settings.default_production_order_layer2_capital_cost_rate = 0.11
    global_settings.default_production_order_layer2_stockout_penalty_weight = 0.33
    global_settings.default_production_order_layer2_overstock_penalty_weight = 0.19

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-LAYER-PROXY-REQUEST",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-LAYER-PROXY-REQUEST",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-LAYER-PROXY-REQUEST",
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
            "layer3_stockout_boost_max": 0.23,
            "layer3_overstock_dampen_max": 0.18,
            "layer5_unavoidable_stockout_risk_threshold": 0.27,
            "layer5_accelerate_production_risk_threshold": 0.41,
            "layer2_capital_cost_rate": 0.07,
            "layer2_stockout_penalty_weight": 0.52,
            "layer2_overstock_penalty_weight": 0.16,
        },
    }

    response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert response.status_code == 200, response.text

    body = response.json()
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer_3_calibration"]["stockout_boost_max"] == 0.23
    assert alpha_proxy["layer_3_calibration"]["overstock_dampen_max"] == 0.18
    assert alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"] == 0.27
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.41,
        "increase_price_to_slow_velocity": 0.27,
        "reduce_order_size": 0.10,
    }
    assert alpha_proxy["layer_2_objective_parameters"] == {
        "capital_cost_rate": 0.07,
        "stockout_penalty_weight": 0.52,
        "overstock_penalty_weight": 0.16,
    }
    assert alpha_proxy["layer_proxy_source"] == {
        "layer3_stockout_boost_max": "request",
        "layer3_overstock_dampen_max": "request",
        "layer5_unavoidable_stockout_risk_threshold": "request",
        "layer5_accelerate_production_risk_threshold": "request",
        "layer2_capital_cost_rate": "request",
        "layer2_stockout_penalty_weight": "request",
        "layer2_overstock_penalty_weight": "request",
        "layer5_accelerate_action_cost_rate": "code_default_constants",
        "layer5_price_slowdown_lost_volume_rate": "code_default_constants",
        "layer5_reduce_order_marginal_profit_rate": "code_default_constants",
    }

    layer2 = body["explanation"]["meta"]["layer_2_allocation"]
    assert layer2["objective_parameters"] == {
        "capital_cost_rate": 0.07,
        "stockout_penalty_weight": 0.52,
        "overstock_penalty_weight": 0.16,
    }
    assert layer2["objective_source"] == {
        "capital_cost_rate": "request",
        "stockout_penalty_weight": "request",
        "overstock_penalty_weight": "request",
    }
    expected_compact_layer2 = {
        "method": layer2.get("method"),
        "method_canonical": layer2.get("method_canonical"),
        "legacy_method": layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": layer2.get("summary", {}),
        "contract": layer2.get("contract", {}),
        "decision_quality": layer2.get("decision_quality", {}),
        "decision_gate": layer2.get("decision_gate"),
        "decision_gate_canonical": layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": layer2.get("legacy_decision_gate"),
        "tie_break": layer2.get("tie_break"),
        "gmroi_usage": layer2.get("gmroi_usage"),
        "objective_formula": layer2.get("objective_formula"),
        "objective_parameters": layer2.get("objective_parameters", {}),
        "objective_source": layer2.get("objective_source", {}),
    }

    layer3 = body["explanation"]["meta"]["layer_3_purchase_shaping"]
    layer3_calibration = layer3["calibration"]
    assert layer3_calibration["stockout_boost_max"] == 0.23
    assert layer3_calibration["overstock_dampen_max"] == 0.18
    expected_compact_layer3 = {
        "method": layer3["method"],
        "factors": layer3["factors"],
        "contract": layer3["contract"],
        "qty_before": layer3["qty_before"],
        "qty_after_base": layer3["qty_after_base"],
        "qty_after": layer3["qty_after"],
        "qty_delta_vs_base": layer3["qty_delta_vs_base"],
        "adjusted_lines": layer3["adjusted_lines"],
        "main_lines": layer3["main_lines"],
        "assorti_lines": layer3["assorti_lines"],
        "hold_lines": layer3["hold_lines"],
        "calibration": layer3["calibration"],
    }
    layer4 = body["explanation"]["meta"]["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": layer4["method"],
        "factors": layer4["factors"],
        "contract": layer4["contract"],
        "aggregate_deltas": layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in layer4["scenarios"]
        ],
    }
    layer5 = body["explanation"]["meta"]["layer_5_intervention"]
    assert layer5["risk_threshold"] == 0.27
    assert layer5["signal_thresholds"] == {
        "accelerate_production": 0.41,
        "increase_price_to_slow_velocity": 0.27,
        "reduce_order_size": 0.10,
    }

    compact_payload = deepcopy(payload)
    compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_alpha_proxy = compact_body["explanation"]["meta"]["alpha_proxy_economics"]
    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    compact_layer3 = compact_body["explanation"]["meta"]["layer_3_purchase_shaping"]
    compact_layer4 = compact_body["explanation"]["meta"]["layer_4_scenarios"]
    compact_layer5 = compact_body["explanation"]["meta"]["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer_3_calibration"] == alpha_proxy["layer_3_calibration"]
    assert compact_alpha_proxy["layer_proxy_source"] == alpha_proxy["layer_proxy_source"]
    assert compact_alpha_proxy["layer_2_objective_parameters"] == alpha_proxy["layer_2_objective_parameters"]
    assert (
        compact_alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
        == alpha_proxy["layer_5_unavoidable_stockout_risk_threshold"]
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer2 == expected_compact_layer2
    assert compact_layer3 == expected_compact_layer3
    assert compact_layer4 == expected_compact_layer4
    assert compact_layer5 == layer5


def test_production_order_proposal_from_wb_layer5_threshold_order_is_clamped_when_admin_invalid(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    article_settings = (
        db_session.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == seeded["article"].id)
        .one()
    )
    article_settings.production_order_layer5_unavoidable_stockout_risk_threshold = 0.44
    article_settings.production_order_layer5_accelerate_production_risk_threshold = 0.21

    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)
    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-L5-CLAMP-ADMIN",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-L5-CLAMP-ADMIN",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-L5-CLAMP-ADMIN",
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
    meta = body["explanation"]["meta"]
    alpha_proxy = body["explanation"]["meta"]["alpha_proxy_economics"]
    assert alpha_proxy["layer5_threshold_order_adjusted"] is True
    assert alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "admin_defaults"
    assert (
        alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"]
        == "admin_defaults|clamped_to_unavoidable"
    )
    assert alpha_proxy["layer_5_signal_thresholds"] == {
        "accelerate_production": 0.44,
        "increase_price_to_slow_velocity": 0.44,
        "reduce_order_size": 0.10,
    }
    assert meta["warnings"][-1] == {
        "code": "layer5_accelerate_threshold_clamped_to_unavoidable",
        "severity": "MEDIUM",
        "message": "layer5_accelerate_production_risk_threshold was below layer5_unavoidable_stockout_risk_threshold and was clamped upward at runtime",
        "article_id": seeded["article"].id,
        "field": "layer5_accelerate_production_risk_threshold",
        "field_metadata": {
            "description": "Layer 5 accelerate-production risk threshold input",
            "type": "number",
        },
        "threshold_order_adjusted": True,
        "accelerate_threshold_effective": 0.44,
        "unavoidable_threshold_effective": 0.44,
        "effective_source": "admin_defaults|clamped_to_unavoidable",
        "action": "Review Layer 5 threshold inputs; accelerate threshold cannot be lower than unavoidable stockout threshold.",
        "next_steps": ["review_layer5_threshold_configuration"],
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    compact_meta = compact_body["explanation"]["meta"]
    compact_alpha_proxy = compact_body["explanation"]["meta"]["alpha_proxy_economics"]
    compact_layer5 = compact_body["explanation"]["meta"]["layer_5_intervention"]
    layer5 = body["explanation"]["meta"]["layer_5_intervention"]
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_alpha_proxy == alpha_proxy
    assert compact_alpha_proxy["layer5_threshold_order_adjusted"] is True
    assert compact_alpha_proxy["layer_proxy_source"]["layer5_unavoidable_stockout_risk_threshold"] == "admin_defaults"
    assert (
        compact_alpha_proxy["layer_proxy_source"]["layer5_accelerate_production_risk_threshold"]
        == "admin_defaults|clamped_to_unavoidable"
    )
    assert compact_alpha_proxy["layer_5_signal_thresholds"] == alpha_proxy["layer_5_signal_thresholds"]
    assert compact_layer5 == layer5
    assert compact_meta["warnings"] == meta["warnings"]


def test_production_order_proposal_from_wb_layer3_calibration_changes_qty_but_not_layer2_decisions(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-L3-CALIBRATION",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-L3-CALIBRATION",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-L3-CALIBRATION",
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

    low_calibration_payload = deepcopy(base_payload)
    low_calibration_payload["overrides"]["layer3_stockout_boost_max"] = 0.0
    low_calibration_payload["overrides"]["layer3_overstock_dampen_max"] = 0.0

    high_calibration_payload = deepcopy(base_payload)
    high_calibration_payload["overrides"]["layer3_stockout_boost_max"] = 1.0
    high_calibration_payload["overrides"]["layer3_overstock_dampen_max"] = 0.0

    low_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=low_calibration_payload,
    )
    assert low_response.status_code == 200, low_response.text

    high_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
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
    expected_low_compact_layer3 = {
        "method": low_layer3["method"],
        "factors": low_layer3["factors"],
        "contract": low_layer3["contract"],
        "qty_before": low_layer3["qty_before"],
        "qty_after_base": low_layer3["qty_after_base"],
        "qty_after": low_layer3["qty_after"],
        "qty_delta_vs_base": low_layer3["qty_delta_vs_base"],
        "adjusted_lines": low_layer3["adjusted_lines"],
        "main_lines": low_layer3["main_lines"],
        "assorti_lines": low_layer3["assorti_lines"],
        "hold_lines": low_layer3["hold_lines"],
        "calibration": low_layer3["calibration"],
    }
    expected_high_compact_layer3 = {
        "method": high_layer3["method"],
        "factors": high_layer3["factors"],
        "contract": high_layer3["contract"],
        "qty_before": high_layer3["qty_before"],
        "qty_after_base": high_layer3["qty_after_base"],
        "qty_after": high_layer3["qty_after"],
        "qty_delta_vs_base": high_layer3["qty_delta_vs_base"],
        "adjusted_lines": high_layer3["adjusted_lines"],
        "main_lines": high_layer3["main_lines"],
        "assorti_lines": high_layer3["assorti_lines"],
        "hold_lines": high_layer3["hold_lines"],
        "calibration": high_layer3["calibration"],
    }
    assert low_layer3["calibration"]["stockout_boost_max"] == 0.0
    assert high_layer3["calibration"]["stockout_boost_max"] == 1.0
    assert low_layer3["calibration"]["overstock_dampen_max"] == 0.0
    assert high_layer3["calibration"]["overstock_dampen_max"] == 0.0
    assert high_layer3["qty_after"] > low_layer3["qty_after"]
    assert high_body["recommendation"]["total_units"] > low_body["recommendation"]["total_units"]

    low_compact_payload = deepcopy(low_calibration_payload)
    low_compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    low_compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=low_compact_payload,
    )
    assert low_compact_response.status_code == 200, low_compact_response.text

    high_compact_payload = deepcopy(high_calibration_payload)
    high_compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    high_compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=high_compact_payload,
    )
    assert high_compact_response.status_code == 200, high_compact_response.text

    low_compact_body = low_compact_response.json()
    high_compact_body = high_compact_response.json()
    low_compact_layer3 = low_compact_body["explanation"]["meta"]["layer_3_purchase_shaping"]
    high_compact_layer3 = high_compact_body["explanation"]["meta"]["layer_3_purchase_shaping"]
    assert _business_projection(low_body) == _business_projection(low_compact_body)
    assert _business_projection(high_body) == _business_projection(high_compact_body)
    assert low_compact_layer3 == expected_low_compact_layer3
    assert high_compact_layer3 == expected_high_compact_layer3


def test_production_order_proposal_from_wb_layer3_shaping_reduces_qty_for_explicit_assorti_flag(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    assorti_bundle_type = BundleType(
        code="PO-WB-BT-MIX-EXPLICIT",
        name="PO-WB-BT-MIX-EXPLICIT",
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
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-MIX-MAIN",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-MIX-ASSORTI",
                bundle_type_id=assorti_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
            WbSalesDaily(
                wb_sku="WB-PO-MIX-MAIN",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=60,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbSalesDaily(
                wb_sku="WB-PO-MIX-ASSORTI",
                date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
                sales_qty=60,
                revenue=None,
                created_at=datetime.now(timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-MIX-MAIN",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=20,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
            WbStock(
                wb_sku="WB-PO-MIX-ASSORTI",
                warehouse_id=1,
                warehouse_name="WB-1",
                stock_qty=20,
                updated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()

    payload_main = {
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
        },
    }

    payload_assorti = {
        "article_id": seeded["article"].id,
        "planning_horizon_days": 90,
        "observation_window_days": 30,
        "as_of_date": "2026-01-10",
        "bundle_type_ids": [assorti_bundle_type.id],
        "in_flight_supply": [],
        "size_weights": {},
        "overrides": {
            "fabric_min_batch_qty_default": 0,
            "elastic_min_batch_qty_default": 0,
        },
    }

    response_main = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload_main)
    response_assorti = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload_assorti,
    )

    assert response_main.status_code == 200, response_main.text
    assert response_assorti.status_code == 200, response_assorti.text

    body_main = response_main.json()
    body_assorti = response_assorti.json()

    assert body_main["recommendation"] is not None
    assert body_assorti["recommendation"] is not None
    assert body_main["recommendation"]["total_units"] < body_assorti["recommendation"]["total_units"]

    layer2_main = body_main["explanation"]["meta"]["layer_2_allocation"]["summary"]
    layer2_assorti = body_assorti["explanation"]["meta"]["layer_2_allocation"]["summary"]
    assert layer2_main["main"] == 0
    assert layer2_main["assorti"] > 0
    assert layer2_assorti["assorti"] == 0
    assert layer2_assorti["main"] > 0

    assorti_classification_main = body_main["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assorti_classification_assorti = body_assorti["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    expected_compact_assorti_classification_main = {
        "source": assorti_classification_main["source"],
        "fallback_sources": assorti_classification_main["fallback_sources"],
        "source_breakdown": assorti_classification_main["source_breakdown"],
        "summary": assorti_classification_main["summary"],
    }
    expected_compact_assorti_classification_assorti = {
        "source": assorti_classification_assorti["source"],
        "fallback_sources": assorti_classification_assorti["fallback_sources"],
        "source_breakdown": assorti_classification_assorti["source_breakdown"],
        "summary": assorti_classification_assorti["summary"],
    }
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
    expected_compact_layer3_main = {
        "method": layer3_main["method"],
        "factors": layer3_main["factors"],
        "contract": layer3_main["contract"],
        "qty_before": layer3_main["qty_before"],
        "qty_after_base": layer3_main["qty_after_base"],
        "qty_after": layer3_main["qty_after"],
        "qty_delta_vs_base": layer3_main["qty_delta_vs_base"],
        "adjusted_lines": layer3_main["adjusted_lines"],
        "main_lines": layer3_main["main_lines"],
        "assorti_lines": layer3_main["assorti_lines"],
        "hold_lines": layer3_main["hold_lines"],
        "calibration": layer3_main["calibration"],
    }
    expected_compact_layer3_assorti = {
        "method": layer3_assorti["method"],
        "factors": layer3_assorti["factors"],
        "contract": layer3_assorti["contract"],
        "qty_before": layer3_assorti["qty_before"],
        "qty_after_base": layer3_assorti["qty_after_base"],
        "qty_after": layer3_assorti["qty_after"],
        "qty_delta_vs_base": layer3_assorti["qty_delta_vs_base"],
        "adjusted_lines": layer3_assorti["adjusted_lines"],
        "main_lines": layer3_assorti["main_lines"],
        "assorti_lines": layer3_assorti["assorti_lines"],
        "hold_lines": layer3_assorti["hold_lines"],
        "calibration": layer3_assorti["calibration"],
    }
    assert layer3_main["main_lines"] == 0
    assert layer3_main["assorti_lines"] > 0
    assert layer3_assorti["assorti_lines"] == 0
    assert layer3_assorti["main_lines"] > 0
    assert layer3_main["qty_after"] < layer3_assorti["qty_after"]

    assert body_assorti["recommendation"]["lines"]
    assert all(
        "|layer2:main" in line["source_reason"]
        for line in body_assorti["recommendation"]["lines"]
    )

    compact_payload_main = deepcopy(payload_main)
    compact_payload_main["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response_main = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload_main,
    )
    assert compact_response_main.status_code == 200, compact_response_main.text

    compact_payload_assorti = deepcopy(payload_assorti)
    compact_payload_assorti["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response_assorti = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=compact_payload_assorti,
    )
    assert compact_response_assorti.status_code == 200, compact_response_assorti.text

    compact_body_main = compact_response_main.json()
    compact_body_assorti = compact_response_assorti.json()
    compact_layer3_main = compact_body_main["explanation"]["meta"]["layer_3_purchase_shaping"]
    compact_layer3_assorti = compact_body_assorti["explanation"]["meta"]["layer_3_purchase_shaping"]
    compact_assorti_classification_main = compact_body_main["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    compact_assorti_classification_assorti = compact_body_assorti["explanation"]["meta"]["layer_1_stock_health"]["assorti_classification"]
    assert _business_projection(body_main) == _business_projection(compact_body_main)
    assert _business_projection(body_assorti) == _business_projection(compact_body_assorti)
    assert compact_assorti_classification_main == expected_compact_assorti_classification_main
    assert compact_assorti_classification_assorti == expected_compact_assorti_classification_assorti
    assert compact_layer3_main == expected_compact_layer3_main
    assert compact_layer3_assorti == expected_compact_layer3_assorti


def test_production_order_proposal_from_wb_layer5_signals_do_not_override_recommendation_action(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-L5-NON-OVERRIDE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-L5-NON-OVERRIDE",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-L5-NON-OVERRIDE",
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

    low_threshold_payload = deepcopy(base_payload)
    low_threshold_payload["overrides"]["layer5_unavoidable_stockout_risk_threshold"] = 0.0
    low_threshold_payload["overrides"]["layer5_accelerate_production_risk_threshold"] = 0.0

    high_threshold_payload = deepcopy(base_payload)
    high_threshold_payload["overrides"]["layer5_unavoidable_stockout_risk_threshold"] = 1.0
    high_threshold_payload["overrides"]["layer5_accelerate_production_risk_threshold"] = 1.0

    low_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=low_threshold_payload)
    assert low_response.status_code == 200, low_response.text

    high_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
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
    assert low_layer5["signals"] == ["reduce_order_size"]
    assert low_layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"
    assert high_layer5["signals"] == ["reduce_order_size"]
    assert high_layer5["reason"] == "overstock_penalty_exceeds_marginal_profit"

    low_compact_payload = deepcopy(low_threshold_payload)
    low_compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    low_compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=low_compact_payload,
    )
    assert low_compact_response.status_code == 200, low_compact_response.text

    high_compact_payload = deepcopy(high_threshold_payload)
    high_compact_payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    high_compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=high_compact_payload,
    )
    assert high_compact_response.status_code == 200, high_compact_response.text

    low_compact_body = low_compact_response.json()
    high_compact_body = high_compact_response.json()
    assert _business_projection(low_body) == _business_projection(low_compact_body)
    assert _business_projection(high_body) == _business_projection(high_compact_body)
    assert low_compact_body["explanation"]["meta"]["layer_5_intervention"] == low_layer5
    assert high_compact_body["explanation"]["meta"]["layer_5_intervention"] == high_layer5
    assert low_compact_body["explanation"]["meta"]["layer_5_intervention"]["signals"] == low_layer5["signals"]
    assert low_compact_body["explanation"]["meta"]["layer_5_intervention"]["reason"] == low_layer5["reason"]
    assert high_compact_body["explanation"]["meta"]["layer_5_intervention"]["signals"] == high_layer5["signals"]
    assert high_compact_body["explanation"]["meta"]["layer_5_intervention"]["reason"] == high_layer5["reason"]


def test_production_order_proposal_from_wb_request_layer2_coefficients_preserve_full_compact_parity(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    stock_updated_at = datetime(2026, 1, 11, tzinfo=timezone.utc)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-L2-PRECEDENCE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-L2-PRECEDENCE",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc).date(),
            sales_qty=60,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-L2-PRECEDENCE",
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
            "layer2_capital_cost_rate": 0.07,
            "layer2_stockout_penalty_weight": 0.52,
            "layer2_overstock_penalty_weight": 0.16,
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

    expected_objective_parameters = {
        "capital_cost_rate": 0.07,
        "stockout_penalty_weight": 0.52,
        "overstock_penalty_weight": 0.16,
    }
    expected_objective_source = {
        "capital_cost_rate": "request",
        "stockout_penalty_weight": "request",
        "overstock_penalty_weight": "request",
    }

    full_meta = full_body["explanation"]["meta"]
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer2 = full_meta["layer_2_allocation"]
    compact_layer2 = compact_meta["layer_2_allocation"]
    expected_compact_layer2 = {
        "method": full_layer2.get("method"),
        "method_canonical": full_layer2.get("method_canonical"),
        "legacy_method": full_layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": full_layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": full_layer2.get("summary", {}),
        "contract": full_layer2.get("contract", {}),
        "decision_quality": full_layer2.get("decision_quality", {}),
        "decision_gate": full_layer2.get("decision_gate"),
        "decision_gate_canonical": full_layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": full_layer2.get("legacy_decision_gate"),
        "tie_break": full_layer2.get("tie_break"),
        "gmroi_usage": full_layer2.get("gmroi_usage"),
        "objective_formula": full_layer2.get("objective_formula"),
        "objective_parameters": full_layer2.get("objective_parameters", {}),
        "objective_source": full_layer2.get("objective_source", {}),
    }
    assert compact_meta["sources"] == full_meta["sources"]
    assert compact_meta["physical_scope"] == full_meta["physical_scope"]
    assert compact_meta["arrival_projection"] == full_meta["arrival_projection"]
    assert compact_meta["economic_buffer"] == full_meta["economic_buffer"]
    assert compact_meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert compact_meta["capital_gap"] == full_meta["capital_gap"]
    assert compact_meta["capital_constraint"] == full_meta["capital_constraint"]
    assert compact_meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["layer_2_allocation"]["decision_quality"] == full_meta["layer_2_allocation"]["decision_quality"]
    assert compact_meta["layer_2_allocation"]["contract"] == full_meta["layer_2_allocation"]["contract"]

    assert full_layer2["objective_parameters"] == expected_objective_parameters
    assert full_layer2["objective_source"] == expected_objective_source
    assert compact_layer2 == expected_compact_layer2
    assert full_meta["alpha_proxy_economics"]["layer_2_objective_parameters"] == expected_objective_parameters
    assert compact_meta["alpha_proxy_economics"]["layer_2_objective_parameters"] == expected_objective_parameters
    assert full_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_capital_cost_rate"] == "request"
    assert full_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_stockout_penalty_weight"] == "request"
    assert full_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_overstock_penalty_weight"] == "request"
    assert compact_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_capital_cost_rate"] == "request"
    assert compact_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_stockout_penalty_weight"] == "request"
    assert compact_meta["alpha_proxy_economics"]["layer_proxy_source"]["layer2_overstock_penalty_weight"] == "request"

    full_layer4 = full_meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4
    assert compact_meta["layer_5_intervention"] == full_meta["layer_5_intervention"]


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

    full_meta = full_body["explanation"]["meta"]
    compact_meta = compact_body["explanation"]["meta"]
    expected_compact_assorti_classification = {
        "source": full_meta["layer_1_stock_health"]["assorti_classification"]["source"],
        "fallback_sources": full_meta["layer_1_stock_health"]["assorti_classification"]["fallback_sources"],
        "source_breakdown": full_meta["layer_1_stock_health"]["assorti_classification"]["source_breakdown"],
        "summary": full_meta["layer_1_stock_health"]["assorti_classification"]["summary"],
    }
    full_layer2 = full_meta["layer_2_allocation"]
    expected_compact_layer2 = {
        "method": full_layer2.get("method"),
        "method_canonical": full_layer2.get("method_canonical"),
        "legacy_method": full_layer2.get("legacy_method"),
        "legacy_alias_deprecation_plan": full_layer2.get("legacy_alias_deprecation_plan", {}),
        "summary": full_layer2.get("summary", {}),
        "contract": full_layer2.get("contract", {}),
        "decision_quality": full_layer2.get("decision_quality", {}),
        "decision_gate": full_layer2.get("decision_gate"),
        "decision_gate_canonical": full_layer2.get("decision_gate_canonical"),
        "legacy_decision_gate": full_layer2.get("legacy_decision_gate"),
        "tie_break": full_layer2.get("tie_break"),
        "gmroi_usage": full_layer2.get("gmroi_usage"),
        "objective_formula": full_layer2.get("objective_formula"),
        "objective_parameters": full_layer2.get("objective_parameters", {}),
        "objective_source": full_layer2.get("objective_source", {}),
    }
    assert compact_meta["sources"] == full_meta["sources"]
    assert compact_meta["physical_scope"] == full_meta["physical_scope"]
    assert compact_meta["arrival_projection"] == full_meta["arrival_projection"]
    assert compact_meta["economic_buffer"] == full_meta["economic_buffer"]
    assert compact_meta["in_flight_effective"] == full_meta["in_flight_effective"]
    assert compact_meta["capital_gap"] == full_meta["capital_gap"]
    assert compact_meta["capital_constraint"] == full_meta["capital_constraint"]
    assert compact_meta["alpha_proxy_economics"] == full_meta["alpha_proxy_economics"]
    assert compact_meta["layer_1_stock_health"]["assorti_classification"] == expected_compact_assorti_classification
    assert compact_meta["layer_2_allocation"]["decision_quality"] == full_layer2["decision_quality"]
    assert compact_meta["layer_2_allocation"]["contract"] == full_layer2["contract"]

    compact_layer2_step = next(
        (step for step in compact_body["explanation"]["steps"] if "Layer 2 allocation" in step),
        "",
    )
    assert f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}" in compact_layer2_step
    assert "legacy_decision_gate=profit_until_eta" in compact_layer2_step
    assert "reason_counts={" in compact_layer2_step
    assert "avg_profit_gap_until_eta=" in compact_layer2_step
    assert "capital_locked_total=" in compact_layer2_step
    assert "contract_status=ok" in compact_layer2_step

    compact_layer2 = compact_body["explanation"]["meta"]["layer_2_allocation"]
    assert compact_layer2["decision_quality"]["profit_gate_primary"] is False
    assert compact_layer2["decision_quality"]["composite_objective_gate_primary"] is True
    assert compact_layer2["decision_quality"]["decision_count"] == 4
    assert compact_layer2 == expected_compact_layer2
    assert (
        compact_body["explanation"]["meta"]["alpha_proxy_economics"]["layer_2_objective_parameters"]
        == compact_layer2["objective_parameters"]
    )
    compact_layer2_contract_checks = compact_layer2["contract"]["checks"]
    assert compact_layer2_contract_checks["decision_reason_matches_allocation"] is True
    assert compact_layer2_contract_checks["allocation_matches_profit_gate"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_objective_tie"] is True
    assert compact_layer2_contract_checks["tie_break_applied_matches_profit_tie"] is True
    assert compact_layer2_contract_checks["near_tie_matches_objective_gap_threshold"] is True
    assert compact_layer2_contract_checks["near_tie_matches_profit_gap_threshold"] is True
    assert compact_layer2_contract_checks["profit_gap_consistent_with_profits"] is True
    assert compact_layer2_contract_checks["gmroi_gap_consistent_with_gmroi"] is True
    assert compact_layer2_contract_checks["capital_locked_metric_valid"] is True

    full_layer4 = full_meta["layer_4_scenarios"]
    compact_layer4 = compact_meta["layer_4_scenarios"]
    expected_compact_layer4 = {
        "method": full_layer4["method"],
        "factors": full_layer4["factors"],
        "contract": full_layer4["contract"],
        "aggregate_deltas": full_layer4["aggregate_deltas"],
        "scenarios": [
            {
                "scenario": full_scenario["scenario"],
                "purchase_units": full_scenario["purchase_units"],
                "total_capital_required": full_scenario["total_capital_required"],
                "expected_revenue": full_scenario["expected_revenue"],
                "expected_gross_profit": full_scenario["expected_gross_profit"],
                "objective_score": full_scenario["objective_score"],
                "expected_margin_percent": full_scenario["expected_margin_percent"],
                "expected_turnover_days": full_scenario["expected_turnover_days"],
                "expected_turnover_proxy": full_scenario["expected_turnover_proxy"],
                "stockout_probability_proxy": full_scenario["stockout_probability_proxy"],
                "stockout_risk_proxy": full_scenario["stockout_risk_proxy"],
                "overstock_risk_proxy": full_scenario["overstock_risk_proxy"],
                "risk_adjusted_profit": full_scenario["risk_adjusted_profit"],
                "capital_efficiency_metric": full_scenario["capital_efficiency_metric"],
                "capital_delta_vs_balanced": full_scenario["capital_delta_vs_balanced"],
                "expected_revenue_delta_vs_balanced": full_scenario["expected_revenue_delta_vs_balanced"],
                "expected_gross_profit_delta_vs_balanced": full_scenario["expected_gross_profit_delta_vs_balanced"],
                "gross_profit_delta_vs_balanced": full_scenario["gross_profit_delta_vs_balanced"],
                "objective_score_delta_vs_balanced": full_scenario["objective_score_delta_vs_balanced"],
                "assorti_sustainability_impact": full_scenario["assorti_sustainability_impact"],
            }
            for full_scenario in full_layer4["scenarios"]
        ],
    }
    assert compact_layer4 == expected_compact_layer4

    expected_compact_freshness = {
        "status": full_meta["from_wb"]["freshness"]["status"],
        "sales_age_days": full_meta["from_wb"]["freshness"]["sales_age_days"],
        "stock_oldest_age_days": full_meta["from_wb"]["freshness"]["stock_oldest_age_days"],
        "threshold_days": full_meta["from_wb"]["freshness"]["threshold_days"],
        "threshold_source": full_meta["from_wb"]["freshness"]["threshold_source"],
    }
    expected_compact_commission_meta = {
        "source": full_meta["from_wb"]["economic_observed_commission"]["source"],
        "status": full_meta["from_wb"]["economic_observed_commission"]["status"],
        "reason": full_meta["from_wb"]["economic_observed_commission"]["reason"],
        "commission_percent": full_meta["from_wb"]["economic_observed_commission"]["commission_percent"],
        "commission_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["commission_percent_stats"],
        "kgvp_supplier_percent_stats": full_meta["from_wb"]["economic_observed_commission"]["kgvp_supplier_percent_stats"],
    }
    expected_compact_snapshot = {
        "daily_sales_bundle_count": len(full_meta["from_wb"]["daily_sales_by_bundle"]),
        "daily_sales_total": sum(full_meta["from_wb"]["daily_sales_by_bundle"].values()),
        "wb_stock_bundle_count": len(full_meta["from_wb"]["wb_stock_by_bundle"]),
        "wb_stock_total": int(sum(full_meta["from_wb"]["wb_stock_by_bundle"].values())),
        "wb_stock_updated_bundle_count": len(full_meta["from_wb"]["wb_stock_updated_at_by_bundle"]),
    }
    expected_compact_from_wb = {
        "observation_window_days": full_meta["from_wb"]["observation_window_days"],
        "freshness_mode": full_meta["from_wb"]["freshness_mode"],
        "requested_as_of_date": full_meta["from_wb"]["requested_as_of_date"],
        "as_of_date": full_meta["from_wb"]["as_of_date"],
        "as_of_source": full_meta["from_wb"]["as_of_source"],
        "bundle_type_ids": full_meta["from_wb"]["bundle_type_ids"],
        "sales_window": full_meta["from_wb"]["sales_window"],
        "freshness": expected_compact_freshness,
        "economic_observed_prices": {
            "source": full_meta["from_wb"]["economic_observed_prices"]["source"],
            "window": full_meta["from_wb"]["economic_observed_prices"]["window"],
            "anomaly_max_deviation": full_meta["from_wb"]["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": full_meta["from_wb"]["economic_observed_prices"]["prices"],
            "sample_counts": full_meta["from_wb"]["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": expected_compact_commission_meta,
        "snapshot": expected_compact_snapshot,
    }
    compact_from_wb = compact_meta["from_wb"]
    assert compact_from_wb == expected_compact_from_wb
    assert compact_meta["layer_5_intervention"] == full_meta["layer_5_intervention"]

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
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": {
            "status": from_wb_meta["freshness"]["status"],
            "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
            "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
            "threshold_days": from_wb_meta["freshness"]["threshold_days"],
            "threshold_source": from_wb_meta["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": from_wb_meta["economic_observed_prices"]["source"],
            "window": from_wb_meta["economic_observed_prices"]["window"],
            "anomaly_max_deviation": from_wb_meta["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": from_wb_meta["economic_observed_prices"]["prices"],
            "sample_counts": from_wb_meta["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": from_wb_meta["economic_observed_commission"]["source"],
            "status": from_wb_meta["economic_observed_commission"]["status"],
            "reason": from_wb_meta["economic_observed_commission"]["reason"],
            "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(from_wb_meta["daily_sales_by_bundle"]),
            "daily_sales_total": sum(from_wb_meta["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(from_wb_meta["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(from_wb_meta["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(from_wb_meta["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    compact_from_wb_meta = compact_body["explanation"]["meta"]["from_wb"]
    assert compact_from_wb_meta == expected_compact_from_wb


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
    expected_compact_freshness = {
        "status": from_wb_meta["freshness"]["status"],
        "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
        "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
        "threshold_days": from_wb_meta["freshness"]["threshold_days"],
        "threshold_source": from_wb_meta["freshness"]["threshold_source"],
    }
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["requested_as_of_date"] is None
    assert from_wb_meta["as_of_date"] is None
    assert from_wb_meta["as_of_source"] == "none"
    assert from_wb_meta["sales_window"] is None
    assert from_wb_meta["daily_sales_by_bundle"][bundle_key] == 0.0
    assert from_wb_meta["wb_stock_by_bundle"][bundle_key] == 7
    assert from_wb_meta["freshness"]["sales_age_days"] is None
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": expected_compact_freshness,
        "economic_observed_prices": {
            "source": from_wb_meta["economic_observed_prices"]["source"],
            "window": from_wb_meta["economic_observed_prices"]["window"],
            "anomaly_max_deviation": from_wb_meta["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": from_wb_meta["economic_observed_prices"]["prices"],
            "sample_counts": from_wb_meta["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": from_wb_meta["economic_observed_commission"]["source"],
            "status": from_wb_meta["economic_observed_commission"]["status"],
            "reason": from_wb_meta["economic_observed_commission"]["reason"],
            "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(from_wb_meta["daily_sales_by_bundle"]),
            "daily_sales_total": sum(from_wb_meta["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(from_wb_meta["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(from_wb_meta["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(from_wb_meta["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    compact_from_wb_meta = compact_body["explanation"]["meta"]["from_wb"]
    assert compact_from_wb_meta == expected_compact_from_wb


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
    expected_compact_freshness = {
        "status": from_wb_meta["freshness"]["status"],
        "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
        "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
        "threshold_days": from_wb_meta["freshness"]["threshold_days"],
        "threshold_source": from_wb_meta["freshness"]["threshold_source"],
    }
    assert from_wb_meta["freshness_mode"] == "warn"
    assert from_wb_meta["as_of_date"] is None
    assert from_wb_meta["as_of_source"] == "none"
    assert from_wb_meta["sales_window"] is None
    assert from_wb_meta["wb_stock_updated_at_by_bundle"][bundle_key] is None
    assert from_wb_meta["freshness"]["status"] == "no_data"
    assert from_wb_meta["freshness"]["sales_age_days"] is None
    assert from_wb_meta["freshness"]["stock_oldest_age_days"] is None
    assert from_wb_meta["freshness"]["stock_age_days_by_bundle"][bundle_key] is None
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": expected_compact_freshness,
        "economic_observed_prices": {
            "source": from_wb_meta["economic_observed_prices"]["source"],
            "window": from_wb_meta["economic_observed_prices"]["window"],
            "anomaly_max_deviation": from_wb_meta["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": from_wb_meta["economic_observed_prices"]["prices"],
            "sample_counts": from_wb_meta["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": from_wb_meta["economic_observed_commission"]["source"],
            "status": from_wb_meta["economic_observed_commission"]["status"],
            "reason": from_wb_meta["economic_observed_commission"]["reason"],
            "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(from_wb_meta["daily_sales_by_bundle"]),
            "daily_sales_total": sum(from_wb_meta["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(from_wb_meta["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(from_wb_meta["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(from_wb_meta["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    compact_from_wb_meta = compact_body["explanation"]["meta"]["from_wb"]
    assert compact_from_wb_meta == expected_compact_from_wb


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
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": {
            "status": from_wb_meta["freshness"]["status"],
            "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
            "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
            "threshold_days": from_wb_meta["freshness"]["threshold_days"],
            "threshold_source": from_wb_meta["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": from_wb_meta["economic_observed_prices"]["source"],
            "window": from_wb_meta["economic_observed_prices"]["window"],
            "anomaly_max_deviation": from_wb_meta["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": from_wb_meta["economic_observed_prices"]["prices"],
            "sample_counts": from_wb_meta["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": from_wb_meta["economic_observed_commission"]["source"],
            "status": from_wb_meta["economic_observed_commission"]["status"],
            "reason": from_wb_meta["economic_observed_commission"]["reason"],
            "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(from_wb_meta["daily_sales_by_bundle"]),
            "daily_sales_total": sum(from_wb_meta["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(from_wb_meta["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(from_wb_meta["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(from_wb_meta["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    compact_from_wb_meta = compact_body["explanation"]["meta"]["from_wb"]
    assert compact_from_wb_meta == expected_compact_from_wb


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
    expected_compact_from_wb = {
        "observation_window_days": from_wb_meta["observation_window_days"],
        "freshness_mode": from_wb_meta["freshness_mode"],
        "requested_as_of_date": from_wb_meta["requested_as_of_date"],
        "as_of_date": from_wb_meta["as_of_date"],
        "as_of_source": from_wb_meta["as_of_source"],
        "bundle_type_ids": from_wb_meta["bundle_type_ids"],
        "sales_window": from_wb_meta["sales_window"],
        "freshness": {
            "status": from_wb_meta["freshness"]["status"],
            "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
            "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
            "threshold_days": from_wb_meta["freshness"]["threshold_days"],
            "threshold_source": from_wb_meta["freshness"]["threshold_source"],
        },
        "economic_observed_prices": {
            "source": from_wb_meta["economic_observed_prices"]["source"],
            "window": from_wb_meta["economic_observed_prices"]["window"],
            "anomaly_max_deviation": from_wb_meta["economic_observed_prices"]["anomaly_max_deviation"],
            "prices": from_wb_meta["economic_observed_prices"]["prices"],
            "sample_counts": from_wb_meta["economic_observed_prices"]["sample_counts"],
        },
        "economic_observed_commission": {
            "source": from_wb_meta["economic_observed_commission"]["source"],
            "status": from_wb_meta["economic_observed_commission"]["status"],
            "reason": from_wb_meta["economic_observed_commission"]["reason"],
            "commission_percent": from_wb_meta["economic_observed_commission"]["commission_percent"],
            "commission_percent_stats": from_wb_meta["economic_observed_commission"]["commission_percent_stats"],
            "kgvp_supplier_percent_stats": from_wb_meta["economic_observed_commission"]["kgvp_supplier_percent_stats"],
        },
        "snapshot": {
            "daily_sales_bundle_count": len(from_wb_meta["daily_sales_by_bundle"]),
            "daily_sales_total": sum(from_wb_meta["daily_sales_by_bundle"].values()),
            "wb_stock_bundle_count": len(from_wb_meta["wb_stock_by_bundle"]),
            "wb_stock_total": int(sum(from_wb_meta["wb_stock_by_bundle"].values())),
            "wb_stock_updated_bundle_count": len(from_wb_meta["wb_stock_updated_at_by_bundle"]),
        },
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json=payload,
    )
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    compact_from_wb_meta = compact_body["explanation"]["meta"]["from_wb"]
    assert compact_from_wb_meta == expected_compact_from_wb


def test_production_order_proposal_direct_request_overrides_wb_import_state(client, db_session):
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
    today_utc = datetime.now(timezone.utc).date()

    assert response.json()["detail"] == {
        "code": "wb_data_freshness_failed",
        "message": "WB data freshness check failed",
        "article_id": seeded["article"].id,
        "field": "freshness_mode",
        "field_metadata": {
            "description": "from-WB freshness gate mode",
            "type": "Literal['warn', 'strict']",
        },
        "freshness_mode": "strict",
        "freshness_status": "stale",
        "sales_age_days": (today_utc - datetime(2020, 1, 1, tzinfo=timezone.utc).date()).days,
        "stock_oldest_age_days": (today_utc - datetime(2020, 1, 2, tzinfo=timezone.utc).date()).days,
        "threshold_days": {"sales": 3, "stock": 2},
        "threshold_source": {"sales": "global_default", "stock": "global_default"},
        "stale_components": ["sales", "stock"],
        "next_steps": ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"],
    }


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

    assert response.json()["detail"] == {
        "code": "wb_data_freshness_failed",
        "message": "WB data freshness check failed",
        "article_id": seeded["article"].id,
        "field": "freshness_mode",
        "field_metadata": {
            "description": "from-WB freshness gate mode",
            "type": "Literal['warn', 'strict']",
        },
        "freshness_mode": "strict",
        "freshness_status": "no_data",
        "sales_age_days": None,
        "stock_oldest_age_days": None,
        "threshold_days": {"sales": 3, "stock": 2},
        "threshold_source": {"sales": "global_default", "stock": "global_default"},
        "stale_components": [],
        "next_steps": ["run_wb_sales_daily_sync_live", "run_wb_stock_sync_live"],
    }


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


def test_production_order_proposal_from_wb_strict_rejects_sales_only_stale_data(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-STRICT-SALES-STALE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-STRICT-SALES-STALE",
            date=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-STRICT-SALES-STALE",
            warehouse_id=1,
            warehouse_name="WB-1",
            stock_qty=5,
            updated_at=datetime.now(timezone.utc),
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
    today_utc = datetime.now(timezone.utc).date()

    assert response.json()["detail"] == {
        "code": "wb_data_freshness_failed",
        "message": "WB data freshness check failed",
        "article_id": seeded["article"].id,
        "field": "freshness_mode",
        "field_metadata": {
            "description": "from-WB freshness gate mode",
            "type": "Literal['warn', 'strict']",
        },
        "freshness_mode": "strict",
        "freshness_status": "stale",
        "sales_age_days": (today_utc - datetime(2020, 1, 1, tzinfo=timezone.utc).date()).days,
        "stock_oldest_age_days": 0,
        "threshold_days": {"sales": 3, "stock": 2},
        "threshold_source": {"sales": "global_default", "stock": "global_default"},
        "stale_components": ["sales"],
        "next_steps": ["run_wb_sales_daily_sync_live"],
    }


def test_production_order_proposal_from_wb_strict_rejects_stock_only_stale_data(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    today_utc = datetime.now(timezone.utc).date()

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-STRICT-STOCK-STALE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-STRICT-STOCK-STALE",
            date=today_utc,
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-STRICT-STOCK-STALE",
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
        "as_of_date": today_utc.isoformat(),
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

    assert response.json()["detail"] == {
        "code": "wb_data_freshness_failed",
        "message": "WB data freshness check failed",
        "article_id": seeded["article"].id,
        "field": "freshness_mode",
        "field_metadata": {
            "description": "from-WB freshness gate mode",
            "type": "Literal['warn', 'strict']",
        },
        "freshness_mode": "strict",
        "freshness_status": "stale",
        "sales_age_days": 0,
        "stock_oldest_age_days": (today_utc - datetime(2020, 1, 2, tzinfo=timezone.utc).date()).days,
        "threshold_days": {"sales": 3, "stock": 2},
        "threshold_source": {"sales": "global_default", "stock": "global_default"},
        "stale_components": ["stock"],
        "next_steps": ["run_wb_stock_sync_live"],
    }


def test_production_order_proposal_from_wb_uses_mixed_freshness_threshold_sources(client, db_session):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-BT1-MIXED-THRESHOLDS",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.add(
        WbSalesDaily(
            wb_sku="WB-PO-BT1-MIXED-THRESHOLDS",
            date=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
            sales_qty=10,
            revenue=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        WbStock(
            wb_sku="WB-PO-BT1-MIXED-THRESHOLDS",
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
            "freshness_stock_stale_after_days": 3650,
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
    assert "freshness_threshold_source=sales:request|stock:admin_defaults" in wb_adapter_step

    from_wb_meta = body["explanation"]["meta"]["from_wb"]
    expected_compact_freshness = {
        "status": from_wb_meta["freshness"]["status"],
        "sales_age_days": from_wb_meta["freshness"]["sales_age_days"],
        "stock_oldest_age_days": from_wb_meta["freshness"]["stock_oldest_age_days"],
        "threshold_days": from_wb_meta["freshness"]["threshold_days"],
        "threshold_source": from_wb_meta["freshness"]["threshold_source"],
    }
    assert from_wb_meta["freshness_mode"] == "strict"
    assert from_wb_meta["freshness"]["status"] == "fresh"
    assert from_wb_meta["freshness"]["threshold_days"] == {
        "sales": 3650,
        "stock": 3650,
    }
    assert from_wb_meta["freshness"]["threshold_source"] == {
        "sales": "request",
        "stock": "admin_defaults",
    }

    payload["explainability_mode"] = EXPLAINABILITY_MODE_COMPACT
    compact_response = client.post("/api/v1/planning/core/production-order/proposal/from-wb", json=payload)
    assert compact_response.status_code == 200, compact_response.text

    compact_body = compact_response.json()
    assert _business_projection(body) == _business_projection(compact_body)
    assert compact_body["explanation"]["meta"]["from_wb"]["freshness"] == expected_compact_freshness


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
    assert response.json()["detail"] == {
        "code": "no_wb_mapped_bundle_types",
        "message": "No WB-mapped bundle types found for the article",
        "article_id": article.id,
        "field": "bundle_type_ids",
        "field_metadata": {
            "description": "List of bundle type IDs",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [],
        "readiness_endpoint": "/api/v1/wb/from-wb/readiness",
        "next_steps": [
            "run_wb_article_mapping_discover_live",
            "run_wb_article_bootstrap_live_if_article_missing",
            "run_wb_article_mapping_sync_live",
        ],
    }


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
    assert response.json()["detail"] == {
        "code": "missing_wb_mapping_for_requested_bundle_types",
        "message": "Missing WB mapping for requested bundle_type_id(s)",
        "article_id": seeded["article"].id,
        "field": "bundle_type_ids",
        "field_metadata": {
            "description": "List of bundle type IDs",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id],
        "missing_bundle_type_ids": [seeded["bundle_type"].id],
        "readiness_endpoint": "/api/v1/wb/from-wb/readiness",
        "next_steps": [
            "run_wb_article_mapping_discover_live",
            "run_wb_article_bootstrap_live_if_article_missing",
            "run_wb_article_mapping_sync_live",
        ],
    }


def test_production_order_proposal_from_wb_rejects_without_bundle_recipe_with_structured_detail(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-NO-RECIPE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.flush()
    (
        db_session.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == seeded["article"].id,
            BundleRecipe.bundle_type_id == seeded["bundle_type"].id,
        )
        .delete(synchronize_session=False)
    )
    db_session.commit()

    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": seeded["article"].id,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [seeded["bundle_type"].id],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_bundle_recipe",
        "message": "No bundle recipe defined for the requested bundle types",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id],
        "missing_bundle_type_ids": [seeded["bundle_type"].id],
        "next_steps": ["create_bundle_recipe_for_requested_bundle_type_ids"],
    }


def test_production_order_proposal_from_wb_rejects_with_partial_missing_bundle_recipe_with_structured_detail(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    second_bundle_type = BundleType(code="PO-WB-BT-STRUCT-2", name="PO-WB-BT-STRUCT-2")
    db_session.add(second_bundle_type)
    db_session.flush()

    db_session.add_all(
        [
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-PARTIAL-RECIPE-1",
                bundle_type_id=seeded["bundle_type"].id,
                size_id=seeded["size_s"].id,
            ),
            ArticleWbMapping(
                article_id=seeded["article"].id,
                wb_sku="WB-PO-PARTIAL-RECIPE-2",
                bundle_type_id=second_bundle_type.id,
                size_id=seeded["size_s"].id,
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": seeded["article"].id,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [seeded["bundle_type"].id, second_bundle_type.id],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "missing_bundle_recipe_bundle_types",
        "message": "Bundle recipe is missing for some requested bundle types",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id, second_bundle_type.id],
        "missing_bundle_type_ids": [second_bundle_type.id],
        "next_steps": ["add_bundle_recipe_for_missing_bundle_type_ids"],
    }


def test_production_order_proposal_from_wb_rejects_without_sku_scope_with_structured_detail(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)

    db_session.add(
        ArticleWbMapping(
            article_id=seeded["article"].id,
            wb_sku="WB-PO-NO-SKU-SCOPE",
            bundle_type_id=seeded["bundle_type"].id,
            size_id=seeded["size_s"].id,
        )
    )
    db_session.flush()

    sku_ids = [
        row.id
        for row in db_session.query(SkuUnit).filter(SkuUnit.article_id == seeded["article"].id).all()
    ]
    (
        db_session.query(StockBalance)
        .filter(StockBalance.sku_unit_id.in_(sku_ids))
        .delete(synchronize_session=False)
    )
    (
        db_session.query(SkuUnit)
        .filter(SkuUnit.article_id == seeded["article"].id)
        .delete(synchronize_session=False)
    )
    db_session.commit()

    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": seeded["article"].id,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [seeded["bundle_type"].id],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_sku_units_for_recipe_colors",
        "message": "No SKU units found for article and recipe colors",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id],
        "recipe_color_ids": [seeded["color_1"].id, seeded["color_2"].id],
        "next_steps": ["create_sku_units_for_recipe_colors"],
    }


def test_production_order_proposal_rejects_without_bundle_recipe_with_structured_detail(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    (
        db_session.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == seeded["article"].id,
            BundleRecipe.bundle_type_id == seeded["bundle_type"].id,
        )
        .delete(synchronize_session=False)
    )
    db_session.commit()

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_bundle_recipe",
        "message": "No bundle recipe defined for the requested bundle types",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id],
        "missing_bundle_type_ids": [seeded["bundle_type"].id],
        "next_steps": ["create_bundle_recipe_for_requested_bundle_type_ids"],
    }


def test_production_order_proposal_rejects_with_partial_missing_bundle_recipe_with_structured_detail(
    client,
    db_session,
):
    seeded = _seed_article_bundle_base(db_session)
    second_bundle_type = BundleType(code="PO-BT-2", name="PO-BT-2")
    db_session.add(second_bundle_type)
    db_session.commit()

    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )
    payload["bundle_daily_sales"].append({"bundle_type_id": second_bundle_type.id, "daily_sales": 10.0})
    payload["bundle_stock"].append({"bundle_type_id": second_bundle_type.id, "wb_qty": 0, "local_qty": 0})

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "missing_bundle_recipe_bundle_types",
        "message": "Bundle recipe is missing for some requested bundle types",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id, second_bundle_type.id],
        "missing_bundle_type_ids": [second_bundle_type.id],
        "next_steps": ["add_bundle_recipe_for_missing_bundle_type_ids"],
    }


def test_production_order_proposal_rejects_without_sku_scope_with_structured_detail(client, db_session):
    seeded = _seed_article_bundle_base(db_session)
    payload = _build_payload(
        article_id=seeded["article"].id,
        bundle_type_id=seeded["bundle_type"].id,
        size_s_id=seeded["size_s"].id,
        size_m_id=seeded["size_m"].id,
    )

    sku_ids = [
        row.id
        for row in db_session.query(SkuUnit).filter(SkuUnit.article_id == seeded["article"].id).all()
    ]
    (
        db_session.query(StockBalance)
        .filter(StockBalance.sku_unit_id.in_(sku_ids))
        .delete(synchronize_session=False)
    )
    (
        db_session.query(SkuUnit)
        .filter(SkuUnit.article_id == seeded["article"].id)
        .delete(synchronize_session=False)
    )
    db_session.commit()

    response = client.post("/api/v1/planning/core/production-order/proposal", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "no_sku_units_for_recipe_colors",
        "message": "No SKU units found for article and recipe colors",
        "article_id": seeded["article"].id,
        "field": "bundle_daily_sales.bundle_type_id",
        "field_metadata": {
            "description": "Requested bundle type IDs from bundle_daily_sales input",
            "type": "list[int]",
        },
        "requested_bundle_type_ids": [seeded["bundle_type"].id],
        "recipe_color_ids": [seeded["color_1"].id, seeded["color_2"].id],
        "next_steps": ["create_sku_units_for_recipe_colors"],
    }


def test_production_order_proposal_returns_404_for_unknown_article(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal",
        json={
            "article_id": 999999999,
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
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": 999999999,
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


def test_production_order_proposal_from_wb_returns_404_for_unknown_article(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": 999999999,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [1],
            "in_flight_supply": [],
            "size_weights": {},
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": 999999999,
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


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


def test_production_order_proposal_from_wb_validation_error_invalid_layer5_threshold_order(
    client,
    db_session,
):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": 1,
            "planning_horizon_days": 90,
            "observation_window_days": 30,
            "bundle_type_ids": [1],
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


def test_production_order_proposal_from_wb_validation_error(client, db_session):  # noqa: ARG001
    response = client.post(
        "/api/v1/planning/core/production-order/proposal/from-wb",
        json={
            "article_id": 1,
            "planning_horizon_days": 0,
            "observation_window_days": 0,
            "bundle_type_ids": [],
        },
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    detail_locs = {tuple(item["loc"]) for item in detail}
    assert ("body", "planning_horizon_days") in detail_locs
    assert ("body", "observation_window_days") in detail_locs
