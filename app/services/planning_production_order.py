from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import floor

from fastapi import HTTPException, status
import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticlePlanningSettings,
    ArticleWbMapping,
    BundleRecipe,
    BundleType,
    Color,
    ColorPlanningSettings,
    ElasticPlanningSettings,
    GlobalPlanningSettings,
    PlanningSettings,
    ProductionOrderElasticBinding,
    ProductionOrderInFlightDefault,
    ProductionOrderSizeWeightSetting,
    SkuUnit,
    StockBalance,
    WbIntegrationAccount,
    WbSalesDaily,
    WbStock,
)
from app.schemas.planning_production_order import (
    BundleDemandInput,
    BundleStockInput,
    ElasticConstraintApplied,
    FabricConstraintApplied,
    PlanningOverridesInput,
    ProductionOrderAlternative,
    ProductionOrderConstraintsApplied,
    ProductionOrderExplanationBlock,
    ProductionOrderProposalFromWbRequest,
    ProductionOrderProposalRequest,
    ProductionOrderProposalResponse,
    ProductionOrderRecommendation,
    ProductionOrderRecommendationLine,
)

FROM_WB_SALES_STALE_AFTER_DAYS = 3
FROM_WB_STOCK_STALE_AFTER_DAYS = 2
FROM_WB_OBSERVED_ECONOMIC_SOURCE = "from_wb_observed_window"
FROM_WB_TARIFFS_COMMISSION_SOURCE = "from_wb_tariffs_commission"
FROM_WB_PRICE_ANOMALY_MAX_DEVIATION = 0.30
FROM_WB_TARIFFS_API_BASE_URL = "https://common-api.wildberries.ru"
FROM_WB_TARIFFS_COMMISSION_PATH = "/api/v1/tariffs/commission"
FROM_WB_TARIFFS_HTTP_TIMEOUT_SECONDS = 20.0
LAYER2_ALLOCATION_METHOD = "time_window_profit_proxy_with_gmroi_diagnostics"
LAYER2_ALLOCATION_METHOD_CANONICAL = "time_window_composite_objective_with_gmroi_diagnostics"
LAYER2_DECISION_GATE_LEGACY = "profit_until_eta"
LAYER2_DECISION_GATE_CANONICAL = "composite_objective_until_eta"
LAYER2_DECISION_REASON_LEGACY_BY_DECISION: dict[str, str] = {
    "main": "profit_main_gt_assorti",
    "assorti": "profit_assorti_gt_main",
    "hold": "profit_tie_hold",
}
LAYER2_DECISION_REASON_CANONICAL_BY_DECISION: dict[str, str] = {
    "main": "expected_gross_profit_main_gt_assorti",
    "assorti": "expected_gross_profit_assorti_gt_main",
    "hold": "expected_gross_profit_tie_hold",
}
LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION: dict[str, str] = {
    "main": "objective_score_main_gt_assorti",
    "assorti": "objective_score_assorti_gt_main",
    "hold": "objective_score_tie_hold",
}
ASSORTI_CLASSIFICATION_SOURCE = "bundle_type.is_assorti"
ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE = "admin_defaults_assorti_mapping"
ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE = "global_default_assorti_mapping"
ASSORTI_CLASSIFICATION_MISSING_SOURCE = "bundle_type_missing_default_main"
EXPLAINABILITY_MODE_FULL = "full"
EXPLAINABILITY_MODE_COMPACT = "compact"
LAYER_PROXY_VALUE_SOURCE = "code_default_constants"
ECONOMICS_FORMULA_VERSION = "v1_economic_alpha"
ECONOMICS_DEFAULT_PRODUCTION_COST_PER_UNIT = 0.8
ECONOMICS_DEFAULT_LOGISTICS_COST_PER_UNIT = 0.2
ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_MAIN = 0.0
ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_ASSORTI = 0.0
ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN = 1.8
ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI = 1.65
ECONOMICS_TRUST_LEVEL_TRUSTED = "trusted"
ECONOMICS_TRUST_LEVEL_PARTIAL = "partial"
ECONOMICS_TRUST_LEVEL_UNTRUSTED = "untrusted"
ECONOMICS_TRUST_KEY_FIELDS: tuple[str, ...] = (
    "wb_commission_percent_main",
    "wb_commission_percent_assorti",
    "production_cost_per_unit",
    "logistics_cost_per_unit",
    "average_realized_price_main",
    "average_realized_price_assorti",
)
ECONOMICS_TRUST_UNTRUSTED_CODE_DEFAULT_THRESHOLD = 2
ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED = "economics_untrusted_defaults_dominant"
ECONOMICS_TRUST_WARNING_CODE_PARTIAL = "economics_partial_defaults_present"
CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT = "missing_available_capital_strict"
LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD = 1.0
LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD = LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
LAYER2_CAPITAL_COST_RATE = 0.08
LAYER2_STOCKOUT_PENALTY_WEIGHT = 1.0
LAYER2_OVERSTOCK_PENALTY_WEIGHT = 1.0
LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW = "2026-12-31"
LAYER2_EXPECTED_GROSS_PROFIT_GATE_LEGACY = "expected_gross_profit_until_eta"
LAYER2_LEGACY_ALIAS_DEPRECATION_POLICY = "non_breaking_aliases_during_transition_window"
LAYER2_LEGACY_DECISION_GATE_ALIASES: tuple[str, ...] = (
    LAYER2_DECISION_GATE_LEGACY,
    LAYER2_EXPECTED_GROSS_PROFIT_GATE_LEGACY,
)
LAYER2_LEGACY_ALIAS_FIELD_REPLACEMENTS: dict[str, str] = {
    "allocation_matches_profit_gate": "allocation_matches_composite_objective_gate",
    "allocation_matches_expected_gross_profit_gate": "allocation_matches_composite_objective_gate",
    "tie_break_hold_when_equal_profit": "tie_break_hold_when_equal_objective",
    "tie_break_applied_matches_profit_tie": "tie_break_applied_matches_objective_tie",
    "near_tie_matches_profit_gap_threshold": "near_tie_matches_objective_gap_threshold",
    "profit_gate_primary": "composite_objective_gate_primary",
    "expected_gross_profit_gate_primary": "composite_objective_gate_primary",
    "near_tie_profit_gap_threshold": "near_tie_objective_gap_threshold",
    "legacy_method": "method_canonical",
    "legacy_decision_gate": "decision_gate_canonical",
    "layer_2_legacy_allocation_method": "layer_2_allocation_method_canonical",
    "layer_2_legacy_decision_gate": "layer_2_decision_gate_canonical",
}
LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD = 0.5
LAYER1_CONTRACT_VERSION = "v1_alpha"
LAYER2_CONTRACT_VERSION = "v1_alpha"
LAYER3_CONTRACT_VERSION = "v1_alpha"
LAYER3_PURCHASE_FACTOR_BY_DECISION: dict[str, float] = {
    "main": 1.0,
    "assorti": 0.75,
    "hold": 0.35,
}
LAYER3_CALIBRATION_METHOD = "risk_weighted_factor_clamp"
LAYER3_STOCKOUT_BOOST_MAX = 0.30
LAYER3_OVERSTOCK_DAMPEN_MAX = 0.40
LAYER3_STOCKOUT_WEIGHT_BY_DECISION: dict[str, float] = {
    "main": 1.0,
    "assorti": 0.7,
    "hold": 0.15,
}
LAYER3_OVERSTOCK_WEIGHT_BY_DECISION: dict[str, float] = {
    "main": 0.35,
    "assorti": 0.6,
    "hold": 1.0,
}
LAYER3_FACTOR_BOUNDS: dict[str, tuple[float, float]] = {
    "main": (0.65, 1.25),
    "assorti": (0.30, 0.95),
    "hold": (0.10, 0.60),
}
LAYER4_SCENARIO_ORDER: tuple[str, ...] = (
    "Conservative",
    "Balanced",
    "Aggressive",
)
LAYER4_CONTRACT_VERSION = "v1_alpha"
LAYER4_SCENARIO_FACTORS: tuple[tuple[str, float], ...] = (
    ("Conservative", 0.80),
    ("Balanced", 1.00),
    ("Aggressive", 1.20),
)
CAPITAL_CONSTRAINT_CONTRACT_VERSION = "v1_alpha"
LAYER5_CONTRACT_VERSION = "v1_alpha"
LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD = 0.25
LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD = 0.35
LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD = LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD
LAYER5_ACCELERATE_ACTION_COST_RATE = 0.20
LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE = 0.15
LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE = 0.10


@dataclass
class _EffectiveSettings:
    include_in_planning: bool
    priority: int
    target_coverage_days: int
    service_level_percent: int
    alert_threshold_days: int
    lead_time_days_total: int
    safety_stock_days: int
    fabric_min_batch_default: int
    elastic_min_batch_default: int
    allow_order_with_buffer: bool


@dataclass
class _EffectiveLayerProxySettings:
    layer3_stockout_boost_max: float
    layer3_overstock_dampen_max: float
    layer5_unavoidable_stockout_risk_threshold: float
    layer5_accelerate_production_risk_threshold: float
    layer2_capital_cost_rate: float
    layer2_stockout_penalty_weight: float
    layer2_overstock_penalty_weight: float
    layer5_accelerate_action_cost_rate: float
    layer5_price_slowdown_lost_volume_rate: float
    layer5_reduce_order_marginal_profit_rate: float
    threshold_order_adjusted: bool
    source: dict[str, str]


@dataclass
class _EffectiveEconomicSettings:
    production_cost_per_unit: float
    logistics_cost_per_unit: float
    wb_commission_percent_main: float
    wb_commission_percent_assorti: float
    average_realized_price_main: float
    average_realized_price_assorti: float
    margin_main_per_unit: float
    margin_assorti_per_unit: float
    unit_capital_per_unit: float
    available_capital: float | None
    calibration_state: str
    source: dict[str, str]


def _ceil_to_int(value: float) -> int:
    as_int = int(value)
    if value > as_int:
        return as_int + 1
    return as_int


def _build_layer2_legacy_alias_deprecation_plan() -> dict[str, object]:
    return {
        "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
        "policy": LAYER2_LEGACY_ALIAS_DEPRECATION_POLICY,
        "canonical_decision_gate": LAYER2_DECISION_GATE_CANONICAL,
        "legacy_decision_gate_aliases": list(LAYER2_LEGACY_DECISION_GATE_ALIASES),
        "field_alias_replacements": dict(LAYER2_LEGACY_ALIAS_FIELD_REPLACEMENTS),
    }


def _normalize_weights(size_ids: list[int], raw_weights: dict[int, float]) -> dict[int, float]:
    if not size_ids:
        return {}

    weights: dict[int, float] = {}
    for size_id in size_ids:
        weight = raw_weights.get(size_id)
        if weight is not None and weight > 0:
            weights[size_id] = float(weight)

    if not weights:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    total = sum(weights.values())
    if total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    normalized = {size_id: weight / total for size_id, weight in weights.items()}

    # Ensure all requested sizes exist in output map.
    for size_id in size_ids:
        normalized.setdefault(size_id, 0.0)

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    return {size_id: normalized[size_id] / norm_total for size_id in size_ids}


def _allocate_units(total_units: int, weights: dict[int, float]) -> dict[int, int]:
    if total_units <= 0 or not weights:
        return {key: 0 for key in weights}

    keys = sorted(weights.keys())
    raw_values: dict[int, float] = {
        key: float(total_units) * max(weights.get(key, 0.0), 0.0) for key in keys
    }

    allocated: dict[int, int] = {key: int(raw_values[key]) for key in keys}
    assigned = sum(allocated.values())
    remainder = max(total_units - assigned, 0)

    if remainder > 0:
        remainders = sorted(
            keys,
            key=lambda key: (raw_values[key] - allocated[key], -key),
            reverse=True,
        )
        for index in range(remainder):
            allocated[remainders[index % len(remainders)]] += 1

    return allocated


def _choose_action(
    risk_level: str,
    candidate_units: int,
    allow_order_with_buffer: bool,
) -> str:
    if candidate_units <= 0:
        return "wait"

    if risk_level in {"critical", "warning"}:
        if allow_order_with_buffer:
            return "order_with_buffer"
        return "order_minimum_only"

    if risk_level in {"overstock", "ok", "no_data"}:
        return "wait"

    return "order_minimum_only"


def _build_alternatives(action: str) -> list[ProductionOrderAlternative]:
    alternatives = {
        "wait": ProductionOrderAlternative(
            action="wait",
            pros=["Минимальная заморозка средств"],
            cons=["Риск недозаказа при резком росте спроса"],
        ),
        "order_with_buffer": ProductionOrderAlternative(
            action="order_with_buffer",
            pros=["Снижает риск OOS до следующего цикла"],
            cons=["Увеличивает объем замороженного капитала"],
        ),
        "order_minimum_only": ProductionOrderAlternative(
            action="order_minimum_only",
            pros=["Соблюдает фабричные минималки без избыточного буфера"],
            cons=["Может не покрыть всплеск спроса"],
        ),
    }

    # Return at least two alternatives, excluding the recommended action from the first slot.
    ordered_actions = ["wait", "order_with_buffer", "order_minimum_only"]
    result: list[ProductionOrderAlternative] = []
    for alt_action in ordered_actions:
        if alt_action == action:
            continue
        result.append(alternatives[alt_action])

    if len(result) < 2:
        for alt_action in ordered_actions:
            if alt_action != action and all(item.action != alt_action for item in result):
                result.append(alternatives[alt_action])
            if len(result) >= 2:
                break

    return result


def _build_effective_settings(
    article_settings: ArticlePlanningSettings | None,
    planning_settings: PlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
) -> _EffectiveSettings:
    target_coverage_days = 60
    service_level_percent = 90
    alert_threshold_days = 90
    safety_stock_days = 0
    fabric_min_batch_default = 7000
    elastic_min_batch_default = 3000

    if global_settings is not None:
        target_coverage_days = global_settings.default_target_coverage_days
        service_level_percent = global_settings.default_service_level_percent
        fabric_min_batch_default = global_settings.default_fabric_min_batch_qty
        elastic_min_batch_default = global_settings.default_elastic_min_batch_qty

    if article_settings is not None:
        if article_settings.target_coverage_days is not None:
            target_coverage_days = article_settings.target_coverage_days
        if article_settings.service_level_percent is not None:
            service_level_percent = article_settings.service_level_percent

    if planning_settings is not None:
        alert_threshold_days = planning_settings.alert_threshold_days
        safety_stock_days = planning_settings.safety_stock_days

    if overrides is not None:
        if overrides.target_coverage_days is not None:
            target_coverage_days = overrides.target_coverage_days
        if overrides.service_level_percent is not None:
            service_level_percent = overrides.service_level_percent
        if overrides.alert_threshold_days is not None:
            alert_threshold_days = overrides.alert_threshold_days
        if overrides.fabric_min_batch_qty_default is not None:
            fabric_min_batch_default = overrides.fabric_min_batch_qty_default
        if overrides.elastic_min_batch_qty_default is not None:
            elastic_min_batch_default = overrides.elastic_min_batch_qty_default

    lead_time_production = 30
    lead_time_china_to_nsk = 30
    lead_time_packaging = 3
    lead_time_nsk_to_wb = 7

    if overrides is not None and overrides.lead_time_days is not None:
        if overrides.lead_time_days.production is not None:
            lead_time_production = overrides.lead_time_days.production
        if overrides.lead_time_days.china_to_nsk is not None:
            lead_time_china_to_nsk = overrides.lead_time_days.china_to_nsk
        if overrides.lead_time_days.packaging is not None:
            lead_time_packaging = overrides.lead_time_days.packaging
        if overrides.lead_time_days.nsk_to_wb is not None:
            lead_time_nsk_to_wb = overrides.lead_time_days.nsk_to_wb

    lead_time_days_total = (
        lead_time_production
        + lead_time_china_to_nsk
        + lead_time_packaging
        + lead_time_nsk_to_wb
    )

    include_in_planning = True
    priority = 0
    if article_settings is not None:
        include_in_planning = article_settings.include_in_planning
        priority = article_settings.priority

    allow_order_with_buffer = True
    if overrides is not None:
        allow_order_with_buffer = overrides.allow_order_with_buffer

    return _EffectiveSettings(
        include_in_planning=include_in_planning,
        priority=priority,
        target_coverage_days=target_coverage_days,
        service_level_percent=service_level_percent,
        alert_threshold_days=alert_threshold_days,
        lead_time_days_total=lead_time_days_total,
        safety_stock_days=safety_stock_days,
        fabric_min_batch_default=fabric_min_batch_default,
        elastic_min_batch_default=elastic_min_batch_default,
        allow_order_with_buffer=allow_order_with_buffer,
    )


def _normalize_unit_interval(value: float | None) -> float | None:
    if value is None:
        return None

    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None

    if normalized < 0.0 or normalized > 1.0:
        return None

    return normalized


def _bounded_unit_float(value: object) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(min(normalized, 1.0), 0.0)


def _compute_objective_components(
    *,
    expected_gross_profit: float,
    capital_locked: float,
    stockout_risk: float,
    overstock_risk: float,
    expected_lost_margin_if_stockout: float,
    inventory_carrying_cost: float,
    capital_cost_rate: float,
    stockout_penalty_weight: float,
    overstock_penalty_weight: float,
    horizon_factor: float,
) -> dict[str, float]:
    expected_profit = max(float(expected_gross_profit), 0.0)
    capital_locked_value = max(float(capital_locked), 0.0)
    stockout_risk_value = _bounded_unit_float(stockout_risk)
    overstock_risk_value = _bounded_unit_float(overstock_risk)
    stockout_loss = max(float(expected_lost_margin_if_stockout), 0.0)
    carrying_cost = max(float(inventory_carrying_cost), 0.0)
    capital_cost_rate_value = max(float(capital_cost_rate), 0.0)
    stockout_weight = max(float(stockout_penalty_weight), 0.0)
    overstock_weight = max(float(overstock_penalty_weight), 0.0)
    horizon_factor_value = max(float(horizon_factor), 0.0)

    capital_cost_penalty = capital_locked_value * capital_cost_rate_value * horizon_factor_value
    stockout_penalty = stockout_risk_value * stockout_loss * stockout_weight
    overstock_penalty = overstock_risk_value * carrying_cost * overstock_weight
    objective_score = (
        expected_profit
        - capital_cost_penalty
        - stockout_penalty
        - overstock_penalty
    )

    return {
        "objective_score": objective_score,
        "capital_cost_penalty": capital_cost_penalty,
        "stockout_penalty": stockout_penalty,
        "overstock_penalty": overstock_penalty,
    }


def _resolve_layer_proxy_float(
    *,
    request_value: float | None,
    admin_value: float | None,
    global_value: float | None,
    code_default: float,
) -> tuple[float, str]:
    request_normalized = _normalize_unit_interval(request_value)
    admin_normalized = _normalize_unit_interval(admin_value)
    global_normalized = _normalize_unit_interval(global_value)

    if request_normalized is not None:
        return request_normalized, "request"
    if admin_normalized is not None:
        return admin_normalized, "admin_defaults"
    if global_normalized is not None:
        return global_normalized, "global_default"
    return float(code_default), LAYER_PROXY_VALUE_SOURCE


def _normalize_non_negative_float(value: object) -> float | None:
    if value is None:
        return None

    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None

    if normalized < 0.0:
        return None
    return normalized


def _resolve_economic_float(
    *,
    request_value: float | None,
    runtime_value: float | None,
    admin_value: float | None,
    global_value: float | None,
    code_default: float,
    runtime_source: str,
) -> tuple[float, str]:
    request_normalized = _normalize_non_negative_float(request_value)
    runtime_normalized = _normalize_non_negative_float(runtime_value)
    admin_normalized = _normalize_non_negative_float(admin_value)
    global_normalized = _normalize_non_negative_float(global_value)

    if request_normalized is not None:
        return request_normalized, "request"
    if runtime_normalized is not None:
        return runtime_normalized, runtime_source
    if admin_normalized is not None:
        return admin_normalized, "admin_defaults"
    if global_normalized is not None:
        return global_normalized, "global_default"
    return float(code_default), LAYER_PROXY_VALUE_SOURCE


def _resolve_optional_economic_float(
    *,
    request_value: float | None,
    admin_value: float | None,
    global_value: float | None,
) -> tuple[float | None, str]:
    request_normalized = _normalize_non_negative_float(request_value)
    admin_normalized = _normalize_non_negative_float(admin_value)
    global_normalized = _normalize_non_negative_float(global_value)

    if request_normalized is not None:
        return request_normalized, "request"
    if admin_normalized is not None:
        return admin_normalized, "admin_defaults"
    if global_normalized is not None:
        return global_normalized, "global_default"
    return None, "not_set"


def _resolve_economic_settings(
    *,
    article_settings: ArticlePlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
    runtime_overrides: dict[str, float | None] | None = None,
    runtime_source: str | None = None,
    runtime_source_overrides: dict[str, str] | None = None,
) -> _EffectiveEconomicSettings:
    request_production_cost = (
        overrides.production_cost_per_unit
        if overrides is not None
        else None
    )
    request_logistics_cost = (
        overrides.logistics_cost_per_unit
        if overrides is not None
        else None
    )
    request_commission_main = (
        overrides.wb_commission_percent_main
        if overrides is not None
        else None
    )
    request_commission_assorti = (
        overrides.wb_commission_percent_assorti
        if overrides is not None
        else None
    )
    request_price_main = (
        overrides.average_realized_price_main
        if overrides is not None
        else None
    )
    request_price_assorti = (
        overrides.average_realized_price_assorti
        if overrides is not None
        else None
    )
    request_available_capital = (
        overrides.available_capital
        if overrides is not None
        else None
    )
    runtime_values = runtime_overrides or {}
    runtime_source_label = runtime_source or FROM_WB_OBSERVED_ECONOMIC_SOURCE
    runtime_source_by_field = runtime_source_overrides or {}

    def _runtime_source_for(field_name: str) -> str:
        source_raw = runtime_source_by_field.get(field_name)
        if isinstance(source_raw, str):
            normalized = source_raw.strip()
            if normalized:
                return normalized
        return runtime_source_label

    runtime_production_cost = runtime_values.get("production_cost_per_unit")
    runtime_logistics_cost = runtime_values.get("logistics_cost_per_unit")
    runtime_commission_main = runtime_values.get("wb_commission_percent_main")
    runtime_commission_assorti = runtime_values.get("wb_commission_percent_assorti")
    runtime_price_main = runtime_values.get("average_realized_price_main")
    runtime_price_assorti = runtime_values.get("average_realized_price_assorti")

    admin_production_cost = (
        getattr(article_settings, "production_order_production_cost_per_unit", None)
        if article_settings is not None
        else None
    )
    admin_logistics_cost = (
        getattr(article_settings, "production_order_logistics_cost_per_unit", None)
        if article_settings is not None
        else None
    )
    admin_commission_main = (
        getattr(article_settings, "production_order_wb_commission_percent_main", None)
        if article_settings is not None
        else None
    )
    admin_commission_assorti = (
        getattr(article_settings, "production_order_wb_commission_percent_assorti", None)
        if article_settings is not None
        else None
    )
    admin_price_main = (
        getattr(article_settings, "production_order_average_realized_price_main", None)
        if article_settings is not None
        else None
    )
    admin_price_assorti = (
        getattr(article_settings, "production_order_average_realized_price_assorti", None)
        if article_settings is not None
        else None
    )
    admin_available_capital = (
        getattr(article_settings, "production_order_available_capital", None)
        if article_settings is not None
        else None
    )

    global_production_cost = (
        getattr(global_settings, "default_production_order_production_cost_per_unit", None)
        if global_settings is not None
        else None
    )
    global_logistics_cost = (
        getattr(global_settings, "default_production_order_logistics_cost_per_unit", None)
        if global_settings is not None
        else None
    )
    global_commission_main = (
        getattr(global_settings, "default_production_order_wb_commission_percent_main", None)
        if global_settings is not None
        else None
    )
    global_commission_assorti = (
        getattr(global_settings, "default_production_order_wb_commission_percent_assorti", None)
        if global_settings is not None
        else None
    )
    global_price_main = (
        getattr(global_settings, "default_production_order_average_realized_price_main", None)
        if global_settings is not None
        else None
    )
    global_price_assorti = (
        getattr(global_settings, "default_production_order_average_realized_price_assorti", None)
        if global_settings is not None
        else None
    )
    global_available_capital = (
        getattr(global_settings, "default_production_order_available_capital", None)
        if global_settings is not None
        else None
    )

    production_cost_per_unit, production_cost_source = _resolve_economic_float(
        request_value=request_production_cost,
        runtime_value=runtime_production_cost,
        admin_value=admin_production_cost,
        global_value=global_production_cost,
        code_default=ECONOMICS_DEFAULT_PRODUCTION_COST_PER_UNIT,
        runtime_source=_runtime_source_for("production_cost_per_unit"),
    )
    logistics_cost_per_unit, logistics_cost_source = _resolve_economic_float(
        request_value=request_logistics_cost,
        runtime_value=runtime_logistics_cost,
        admin_value=admin_logistics_cost,
        global_value=global_logistics_cost,
        code_default=ECONOMICS_DEFAULT_LOGISTICS_COST_PER_UNIT,
        runtime_source=_runtime_source_for("logistics_cost_per_unit"),
    )
    wb_commission_percent_main, wb_commission_main_source = _resolve_economic_float(
        request_value=request_commission_main,
        runtime_value=runtime_commission_main,
        admin_value=admin_commission_main,
        global_value=global_commission_main,
        code_default=ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_MAIN,
        runtime_source=_runtime_source_for("wb_commission_percent_main"),
    )
    wb_commission_percent_assorti, wb_commission_assorti_source = _resolve_economic_float(
        request_value=request_commission_assorti,
        runtime_value=runtime_commission_assorti,
        admin_value=admin_commission_assorti,
        global_value=global_commission_assorti,
        code_default=ECONOMICS_DEFAULT_WB_COMMISSION_PERCENT_ASSORTI,
        runtime_source=_runtime_source_for("wb_commission_percent_assorti"),
    )
    average_realized_price_main, price_main_source = _resolve_economic_float(
        request_value=request_price_main,
        runtime_value=runtime_price_main,
        admin_value=admin_price_main,
        global_value=global_price_main,
        code_default=ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN,
        runtime_source=_runtime_source_for("average_realized_price_main"),
    )
    average_realized_price_assorti, price_assorti_source = _resolve_economic_float(
        request_value=request_price_assorti,
        runtime_value=runtime_price_assorti,
        admin_value=admin_price_assorti,
        global_value=global_price_assorti,
        code_default=ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI,
        runtime_source=_runtime_source_for("average_realized_price_assorti"),
    )
    available_capital, available_capital_source = _resolve_optional_economic_float(
        request_value=request_available_capital,
        admin_value=admin_available_capital,
        global_value=global_available_capital,
    )

    wb_commission_percent_main = max(min(wb_commission_percent_main, 1.0), 0.0)
    wb_commission_percent_assorti = max(min(wb_commission_percent_assorti, 1.0), 0.0)

    commission_main_amount = average_realized_price_main * wb_commission_percent_main
    commission_assorti_amount = average_realized_price_assorti * wb_commission_percent_assorti
    margin_main_per_unit = max(
        average_realized_price_main - commission_main_amount - production_cost_per_unit - logistics_cost_per_unit,
        0.0,
    )
    margin_assorti_per_unit = max(
        average_realized_price_assorti - commission_assorti_amount - production_cost_per_unit - logistics_cost_per_unit,
        0.0,
    )
    unit_capital_per_unit = max(production_cost_per_unit + logistics_cost_per_unit, 0.0)

    source = {
        "production_cost_per_unit": production_cost_source,
        "logistics_cost_per_unit": logistics_cost_source,
        "wb_commission_percent_main": wb_commission_main_source,
        "wb_commission_percent_assorti": wb_commission_assorti_source,
        "average_realized_price_main": price_main_source,
        "average_realized_price_assorti": price_assorti_source,
        "available_capital": available_capital_source,
    }
    calibrated_sources = [
        source["production_cost_per_unit"],
        source["logistics_cost_per_unit"],
        source["wb_commission_percent_main"],
        source["wb_commission_percent_assorti"],
        source["average_realized_price_main"],
        source["average_realized_price_assorti"],
    ]
    calibration_state = (
        "economic_inputs_calibrated"
        if any(item != LAYER_PROXY_VALUE_SOURCE for item in calibrated_sources)
        else "economic_inputs_default_formula"
    )

    return _EffectiveEconomicSettings(
        production_cost_per_unit=round(production_cost_per_unit, 4),
        logistics_cost_per_unit=round(logistics_cost_per_unit, 4),
        wb_commission_percent_main=round(wb_commission_percent_main, 4),
        wb_commission_percent_assorti=round(wb_commission_percent_assorti, 4),
        average_realized_price_main=round(average_realized_price_main, 4),
        average_realized_price_assorti=round(average_realized_price_assorti, 4),
        margin_main_per_unit=round(margin_main_per_unit, 4),
        margin_assorti_per_unit=round(margin_assorti_per_unit, 4),
        unit_capital_per_unit=round(unit_capital_per_unit, 4),
        available_capital=round(available_capital, 4) if available_capital is not None else None,
        calibration_state=calibration_state,
        source=source,
    )


def _build_economics_trust_diagnostics(economic_source: dict[str, str]) -> dict[str, object]:
    key_field_sources = {
        field_name: str(economic_source.get(field_name, "unknown"))
        for field_name in ECONOMICS_TRUST_KEY_FIELDS
    }
    code_default_key_fields = sorted(
        field_name
        for field_name, source in key_field_sources.items()
        if source == LAYER_PROXY_VALUE_SOURCE
    )
    code_default_key_fields_count = len(code_default_key_fields)
    key_fields_total = len(ECONOMICS_TRUST_KEY_FIELDS)
    code_default_dominance_ratio = (
        round(code_default_key_fields_count / key_fields_total, 4)
        if key_fields_total > 0
        else 0.0
    )

    if code_default_key_fields_count >= ECONOMICS_TRUST_UNTRUSTED_CODE_DEFAULT_THRESHOLD:
        trust_level = ECONOMICS_TRUST_LEVEL_UNTRUSTED
    elif code_default_key_fields_count == 0:
        trust_level = ECONOMICS_TRUST_LEVEL_TRUSTED
    else:
        trust_level = ECONOMICS_TRUST_LEVEL_PARTIAL

    warnings: list[dict[str, object]] = []
    if trust_level == ECONOMICS_TRUST_LEVEL_UNTRUSTED:
        warnings.append(
            {
                "code": ECONOMICS_TRUST_WARNING_CODE_UNTRUSTED,
                "severity": "HIGH",
                "message": (
                    "Economics trust level is untrusted because key economics inputs are dominated "
                    "by code defaults."
                ),
                "code_default_key_fields": code_default_key_fields,
            }
        )
    elif trust_level == ECONOMICS_TRUST_LEVEL_PARTIAL:
        warnings.append(
            {
                "code": ECONOMICS_TRUST_WARNING_CODE_PARTIAL,
                "severity": "MEDIUM",
                "message": (
                    "Economics trust level is partial because some key economics inputs still use "
                    "code defaults."
                ),
                "code_default_key_fields": code_default_key_fields,
            }
        )

    return {
        "economics_trust_level": trust_level,
        "key_fields": list(ECONOMICS_TRUST_KEY_FIELDS),
        "key_field_sources": key_field_sources,
        "code_default_key_fields": code_default_key_fields,
        "code_default_key_fields_count": code_default_key_fields_count,
        "code_default_dominance_ratio": code_default_dominance_ratio,
        "warnings": warnings,
    }


def _resolve_layer_proxy_settings(
    *,
    article_settings: ArticlePlanningSettings | None,
    global_settings: GlobalPlanningSettings | None,
    overrides: PlanningOverridesInput | None,
) -> _EffectiveLayerProxySettings:
    request_layer3_stockout_boost = (
        overrides.layer3_stockout_boost_max
        if overrides is not None
        else None
    )
    request_layer3_overstock_dampen = (
        overrides.layer3_overstock_dampen_max
        if overrides is not None
        else None
    )
    request_layer5_unavoidable_threshold = (
        overrides.layer5_unavoidable_stockout_risk_threshold
        if overrides is not None
        else None
    )
    request_layer5_accelerate_threshold = (
        overrides.layer5_accelerate_production_risk_threshold
        if overrides is not None
        else None
    )
    request_layer2_capital_cost_rate = (
        overrides.layer2_capital_cost_rate
        if overrides is not None
        else None
    )
    request_layer2_stockout_penalty_weight = (
        overrides.layer2_stockout_penalty_weight
        if overrides is not None
        else None
    )
    request_layer2_overstock_penalty_weight = (
        overrides.layer2_overstock_penalty_weight
        if overrides is not None
        else None
    )
    request_layer5_accelerate_action_cost_rate = (
        overrides.layer5_accelerate_action_cost_rate
        if overrides is not None
        else None
    )
    request_layer5_price_slowdown_lost_volume_rate = (
        overrides.layer5_price_slowdown_lost_volume_rate
        if overrides is not None
        else None
    )
    request_layer5_reduce_order_marginal_profit_rate = (
        overrides.layer5_reduce_order_marginal_profit_rate
        if overrides is not None
        else None
    )

    admin_layer3_stockout_boost = (
        article_settings.production_order_layer3_stockout_boost_max
        if article_settings is not None
        else None
    )
    admin_layer3_overstock_dampen = (
        article_settings.production_order_layer3_overstock_dampen_max
        if article_settings is not None
        else None
    )
    admin_layer5_unavoidable_threshold = (
        article_settings.production_order_layer5_unavoidable_stockout_risk_threshold
        if article_settings is not None
        else None
    )
    admin_layer5_accelerate_threshold = (
        article_settings.production_order_layer5_accelerate_production_risk_threshold
        if article_settings is not None
        else None
    )
    admin_layer2_capital_cost_rate = (
        getattr(article_settings, "production_order_layer2_capital_cost_rate", None)
        if article_settings is not None
        else None
    )
    admin_layer2_stockout_penalty_weight = (
        getattr(article_settings, "production_order_layer2_stockout_penalty_weight", None)
        if article_settings is not None
        else None
    )
    admin_layer2_overstock_penalty_weight = (
        getattr(article_settings, "production_order_layer2_overstock_penalty_weight", None)
        if article_settings is not None
        else None
    )
    admin_layer5_accelerate_action_cost_rate = (
        getattr(article_settings, "production_order_layer5_accelerate_action_cost_rate", None)
        if article_settings is not None
        else None
    )
    admin_layer5_price_slowdown_lost_volume_rate = (
        getattr(article_settings, "production_order_layer5_price_slowdown_lost_volume_rate", None)
        if article_settings is not None
        else None
    )
    admin_layer5_reduce_order_marginal_profit_rate = (
        getattr(article_settings, "production_order_layer5_reduce_order_marginal_profit_rate", None)
        if article_settings is not None
        else None
    )

    global_layer3_stockout_boost = (
        global_settings.default_production_order_layer3_stockout_boost_max
        if global_settings is not None
        else None
    )
    global_layer3_overstock_dampen = (
        global_settings.default_production_order_layer3_overstock_dampen_max
        if global_settings is not None
        else None
    )
    global_layer5_unavoidable_threshold = (
        global_settings.default_production_order_layer5_unavoidable_stockout_risk_threshold
        if global_settings is not None
        else None
    )
    global_layer5_accelerate_threshold = (
        global_settings.default_production_order_layer5_accelerate_production_risk_threshold
        if global_settings is not None
        else None
    )
    global_layer2_capital_cost_rate = (
        getattr(global_settings, "default_production_order_layer2_capital_cost_rate", None)
        if global_settings is not None
        else None
    )
    global_layer2_stockout_penalty_weight = (
        getattr(global_settings, "default_production_order_layer2_stockout_penalty_weight", None)
        if global_settings is not None
        else None
    )
    global_layer2_overstock_penalty_weight = (
        getattr(global_settings, "default_production_order_layer2_overstock_penalty_weight", None)
        if global_settings is not None
        else None
    )
    global_layer5_accelerate_action_cost_rate = (
        getattr(global_settings, "default_production_order_layer5_accelerate_action_cost_rate", None)
        if global_settings is not None
        else None
    )
    global_layer5_price_slowdown_lost_volume_rate = (
        getattr(global_settings, "default_production_order_layer5_price_slowdown_lost_volume_rate", None)
        if global_settings is not None
        else None
    )
    global_layer5_reduce_order_marginal_profit_rate = (
        getattr(global_settings, "default_production_order_layer5_reduce_order_marginal_profit_rate", None)
        if global_settings is not None
        else None
    )

    layer3_stockout_boost_max, layer3_stockout_source = _resolve_layer_proxy_float(
        request_value=request_layer3_stockout_boost,
        admin_value=admin_layer3_stockout_boost,
        global_value=global_layer3_stockout_boost,
        code_default=LAYER3_STOCKOUT_BOOST_MAX,
    )
    layer3_overstock_dampen_max, layer3_overstock_source = _resolve_layer_proxy_float(
        request_value=request_layer3_overstock_dampen,
        admin_value=admin_layer3_overstock_dampen,
        global_value=global_layer3_overstock_dampen,
        code_default=LAYER3_OVERSTOCK_DAMPEN_MAX,
    )
    layer5_unavoidable_threshold, layer5_unavoidable_source = _resolve_layer_proxy_float(
        request_value=request_layer5_unavoidable_threshold,
        admin_value=admin_layer5_unavoidable_threshold,
        global_value=global_layer5_unavoidable_threshold,
        code_default=LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
    )
    layer5_accelerate_threshold, layer5_accelerate_source = _resolve_layer_proxy_float(
        request_value=request_layer5_accelerate_threshold,
        admin_value=admin_layer5_accelerate_threshold,
        global_value=global_layer5_accelerate_threshold,
        code_default=LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    )
    layer2_capital_cost_rate, layer2_capital_cost_rate_source = _resolve_layer_proxy_float(
        request_value=request_layer2_capital_cost_rate,
        admin_value=admin_layer2_capital_cost_rate,
        global_value=global_layer2_capital_cost_rate,
        code_default=LAYER2_CAPITAL_COST_RATE,
    )
    layer2_stockout_penalty_weight, layer2_stockout_penalty_weight_source = _resolve_layer_proxy_float(
        request_value=request_layer2_stockout_penalty_weight,
        admin_value=admin_layer2_stockout_penalty_weight,
        global_value=global_layer2_stockout_penalty_weight,
        code_default=LAYER2_STOCKOUT_PENALTY_WEIGHT,
    )
    layer2_overstock_penalty_weight, layer2_overstock_penalty_weight_source = _resolve_layer_proxy_float(
        request_value=request_layer2_overstock_penalty_weight,
        admin_value=admin_layer2_overstock_penalty_weight,
        global_value=global_layer2_overstock_penalty_weight,
        code_default=LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    )
    layer5_accelerate_action_cost_rate, layer5_accelerate_action_cost_rate_source = _resolve_layer_proxy_float(
        request_value=request_layer5_accelerate_action_cost_rate,
        admin_value=admin_layer5_accelerate_action_cost_rate,
        global_value=global_layer5_accelerate_action_cost_rate,
        code_default=LAYER5_ACCELERATE_ACTION_COST_RATE,
    )
    (
        layer5_price_slowdown_lost_volume_rate,
        layer5_price_slowdown_lost_volume_rate_source,
    ) = _resolve_layer_proxy_float(
        request_value=request_layer5_price_slowdown_lost_volume_rate,
        admin_value=admin_layer5_price_slowdown_lost_volume_rate,
        global_value=global_layer5_price_slowdown_lost_volume_rate,
        code_default=LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE,
    )
    (
        layer5_reduce_order_marginal_profit_rate,
        layer5_reduce_order_marginal_profit_rate_source,
    ) = _resolve_layer_proxy_float(
        request_value=request_layer5_reduce_order_marginal_profit_rate,
        admin_value=admin_layer5_reduce_order_marginal_profit_rate,
        global_value=global_layer5_reduce_order_marginal_profit_rate,
        code_default=LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    )

    threshold_order_adjusted = False
    if layer5_accelerate_threshold < layer5_unavoidable_threshold:
        layer5_accelerate_threshold = layer5_unavoidable_threshold
        threshold_order_adjusted = True
        layer5_accelerate_source = f"{layer5_accelerate_source}|clamped_to_unavoidable"

    return _EffectiveLayerProxySettings(
        layer3_stockout_boost_max=layer3_stockout_boost_max,
        layer3_overstock_dampen_max=layer3_overstock_dampen_max,
        layer5_unavoidable_stockout_risk_threshold=layer5_unavoidable_threshold,
        layer5_accelerate_production_risk_threshold=layer5_accelerate_threshold,
        layer2_capital_cost_rate=layer2_capital_cost_rate,
        layer2_stockout_penalty_weight=layer2_stockout_penalty_weight,
        layer2_overstock_penalty_weight=layer2_overstock_penalty_weight,
        layer5_accelerate_action_cost_rate=layer5_accelerate_action_cost_rate,
        layer5_price_slowdown_lost_volume_rate=layer5_price_slowdown_lost_volume_rate,
        layer5_reduce_order_marginal_profit_rate=layer5_reduce_order_marginal_profit_rate,
        threshold_order_adjusted=threshold_order_adjusted,
        source={
            "layer3_stockout_boost_max": layer3_stockout_source,
            "layer3_overstock_dampen_max": layer3_overstock_source,
            "layer5_unavoidable_stockout_risk_threshold": layer5_unavoidable_source,
            "layer5_accelerate_production_risk_threshold": layer5_accelerate_source,
            "layer2_capital_cost_rate": layer2_capital_cost_rate_source,
            "layer2_stockout_penalty_weight": layer2_stockout_penalty_weight_source,
            "layer2_overstock_penalty_weight": layer2_overstock_penalty_weight_source,
            "layer5_accelerate_action_cost_rate": layer5_accelerate_action_cost_rate_source,
            "layer5_price_slowdown_lost_volume_rate": (
                layer5_price_slowdown_lost_volume_rate_source
            ),
            "layer5_reduce_order_marginal_profit_rate": (
                layer5_reduce_order_marginal_profit_rate_source
            ),
        },
    )


def _add_units_for_color(
    line_qty: dict[tuple[int, int], int],
    color_id: int,
    additional_qty: int,
    color_to_sizes: dict[int, list[int]],
    global_size_weights: dict[int, float],
) -> None:
    if additional_qty <= 0:
        return

    sizes = color_to_sizes.get(color_id, [])
    if not sizes:
        return

    local_weights = _normalize_weights(sizes, global_size_weights)
    allocated = _allocate_units(additional_qty, local_weights)

    for size_id, qty in allocated.items():
        if qty <= 0:
            continue
        key = (color_id, size_id)
        line_qty[key] = line_qty.get(key, 0) + qty


def _parse_assorti_bundle_type_ids(raw_value: str | None) -> set[int]:
    if raw_value is None:
        return set()

    bundle_type_ids: set[int] = set()
    for token in raw_value.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            bundle_type_id = int(candidate)
        except ValueError:
            continue
        if bundle_type_id <= 0:
            continue
        bundle_type_ids.add(bundle_type_id)

    return bundle_type_ids


def _compact_explanation_steps(steps: list[str]) -> tuple[list[str], int]:
    if not steps:
        return [], 0

    keep_tokens = (
        "WB ingestion adapter",
        "Спрос по наборам",
        "Источник параметров",
        "Economics trust",
        "Assorti classification",
        "Layer 1 stock health",
        "Layer 2 allocation",
        "Layer 3 purchase shaping",
        "Layer 4 scenarios",
        "Capital constraint",
        "Layer 5 intervention",
        "Применены ограничения",
    )

    compact_steps = [
        step
        for step in steps
        if any(token in step for token in keep_tokens)
    ]
    if not compact_steps:
        compact_steps = steps[: min(len(steps), 6)]

    compact_steps = compact_steps[:10]
    omitted_steps = max(len(steps) - len(compact_steps), 0)
    if omitted_steps > 0:
        compact_steps.append(
            f"Explainability compact mode: omitted_steps={omitted_steps}."
        )

    return compact_steps, omitted_steps


def _sum_numeric_mapping_values(value: object) -> float:
    if not isinstance(value, dict):
        return 0.0

    total = 0.0
    for item in value.values():
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            total += float(item)

    return round(total, 4)


def _build_compact_explanation_meta(meta: dict[str, object]) -> dict[str, object]:
    compact_meta: dict[str, object] = {
        "warnings": meta.get("warnings", []),
        "economics_trust": meta.get("economics_trust", {}),
        "sources": meta.get("sources", {}),
        "reorder_policy": meta.get("reorder_policy", {}),
        "economic_buffer": meta.get("economic_buffer", {}),
        "in_flight_effective": meta.get("in_flight_effective", {}),
        "capital_gap": meta.get("capital_gap", {}),
        "capital_constraint": meta.get("capital_constraint", {}),
        "alpha_proxy_economics": meta.get("alpha_proxy_economics", {}),
    }

    layer1_raw = meta.get("layer_1_stock_health")
    if isinstance(layer1_raw, dict):
        assorti_raw = layer1_raw.get("assorti_classification")
        assorti_compact: dict[str, object] = {}
        if isinstance(assorti_raw, dict):
            assorti_compact = {
                "source": assorti_raw.get("source"),
                "fallback_sources": assorti_raw.get("fallback_sources", []),
                "source_breakdown": assorti_raw.get("source_breakdown", {}),
                "summary": assorti_raw.get("summary", {}),
            }

        compact_meta["layer_1_stock_health"] = {
            "summary": layer1_raw.get("summary", {}),
            "contract": layer1_raw.get("contract", {}),
            "assorti_classification": assorti_compact,
            "proxies": layer1_raw.get("proxies", {}),
        }

    layer2_raw = meta.get("layer_2_allocation")
    if isinstance(layer2_raw, dict):
        compact_meta["layer_2_allocation"] = {
            "method": layer2_raw.get("method"),
            "method_canonical": layer2_raw.get("method_canonical"),
            "legacy_method": layer2_raw.get("legacy_method"),
            "legacy_alias_deprecation_plan": layer2_raw.get("legacy_alias_deprecation_plan", {}),
            "summary": layer2_raw.get("summary", {}),
            "contract": layer2_raw.get("contract", {}),
            "decision_quality": layer2_raw.get("decision_quality", {}),
            "decision_gate": layer2_raw.get("decision_gate"),
            "decision_gate_canonical": layer2_raw.get("decision_gate_canonical"),
            "legacy_decision_gate": layer2_raw.get("legacy_decision_gate"),
            "tie_break": layer2_raw.get("tie_break"),
            "gmroi_usage": layer2_raw.get("gmroi_usage"),
            "objective_formula": layer2_raw.get("objective_formula"),
            "objective_parameters": layer2_raw.get("objective_parameters", {}),
            "objective_source": layer2_raw.get("objective_source", {}),
        }

    layer3_raw = meta.get("layer_3_purchase_shaping")
    if isinstance(layer3_raw, dict):
        compact_meta["layer_3_purchase_shaping"] = {
            "method": layer3_raw.get("method"),
            "factors": layer3_raw.get("factors", {}),
            "contract": layer3_raw.get("contract", {}),
            "qty_before": layer3_raw.get("qty_before", 0),
            "qty_after_base": layer3_raw.get("qty_after_base", 0),
            "qty_after": layer3_raw.get("qty_after", 0),
            "qty_delta_vs_base": layer3_raw.get("qty_delta_vs_base", 0),
            "adjusted_lines": layer3_raw.get("adjusted_lines", 0),
            "main_lines": layer3_raw.get("main_lines", 0),
            "assorti_lines": layer3_raw.get("assorti_lines", 0),
            "hold_lines": layer3_raw.get("hold_lines", 0),
            "calibration": layer3_raw.get("calibration", {}),
        }

    layer4_raw = meta.get("layer_4_scenarios")
    if isinstance(layer4_raw, dict):
        scenarios_compact: list[dict[str, object]] = []
        scenarios_raw = layer4_raw.get("scenarios")
        if isinstance(scenarios_raw, list):
            for scenario in scenarios_raw:
                if not isinstance(scenario, dict):
                    continue
                scenarios_compact.append(
                    {
                        "scenario": scenario.get("scenario"),
                        "purchase_units": scenario.get("purchase_units"),
                        "total_capital_required": scenario.get("total_capital_required"),
                        "expected_revenue": scenario.get("expected_revenue"),
                        "expected_gross_profit": scenario.get("expected_gross_profit"),
                        "objective_score": scenario.get("objective_score"),
                        "expected_margin_percent": scenario.get("expected_margin_percent"),
                        "expected_turnover_days": scenario.get("expected_turnover_days"),
                        "expected_turnover_proxy": scenario.get("expected_turnover_proxy"),
                        "stockout_probability_proxy": scenario.get("stockout_probability_proxy"),
                        "stockout_risk_proxy": scenario.get("stockout_risk_proxy"),
                        "overstock_risk_proxy": scenario.get("overstock_risk_proxy"),
                        "risk_adjusted_profit": scenario.get("risk_adjusted_profit"),
                        "capital_efficiency_metric": scenario.get("capital_efficiency_metric"),
                        "capital_delta_vs_balanced": scenario.get("capital_delta_vs_balanced"),
                        "expected_revenue_delta_vs_balanced": scenario.get(
                            "expected_revenue_delta_vs_balanced"
                        ),
                        "expected_gross_profit_delta_vs_balanced": scenario.get(
                            "expected_gross_profit_delta_vs_balanced"
                        ),
                        "gross_profit_delta_vs_balanced": scenario.get("gross_profit_delta_vs_balanced"),
                        "objective_score_delta_vs_balanced": (
                            scenario.get("objective_score_delta_vs_balanced")
                        ),
                        "assorti_sustainability_impact": scenario.get("assorti_sustainability_impact"),
                    }
                )

        compact_meta["layer_4_scenarios"] = {
            "method": layer4_raw.get("method"),
            "factors": layer4_raw.get("factors", []),
            "contract": layer4_raw.get("contract", {}),
            "aggregate_deltas": layer4_raw.get("aggregate_deltas", {}),
            "scenarios": scenarios_compact,
        }

    layer5_raw = meta.get("layer_5_intervention")
    if isinstance(layer5_raw, dict):
        compact_meta["layer_5_intervention"] = layer5_raw

    elastic_scope_raw = meta.get("elastic_scope")
    if isinstance(elastic_scope_raw, dict):
        compact_meta["elastic_scope"] = elastic_scope_raw

    elastic_uplift_raw = meta.get("elastic_uplift")
    if isinstance(elastic_uplift_raw, dict):
        compact_meta["elastic_uplift"] = {
            "delta": elastic_uplift_raw.get("delta", 0),
            "scope": elastic_uplift_raw.get("scope", "none"),
            "affected_lines": elastic_uplift_raw.get("affected_lines", 0),
        }

    from_wb_raw = meta.get("from_wb")
    if isinstance(from_wb_raw, dict):
        freshness_raw = from_wb_raw.get("freshness")
        economic_observed_raw = from_wb_raw.get("economic_observed_prices")
        economic_commission_raw = from_wb_raw.get("economic_observed_commission")
        freshness_compact: dict[str, object] = {}
        economic_observed_compact: dict[str, object] = {}
        economic_commission_compact: dict[str, object] = {}
        if isinstance(freshness_raw, dict):
            freshness_compact = {
                "status": freshness_raw.get("status"),
                "sales_age_days": freshness_raw.get("sales_age_days"),
                "stock_oldest_age_days": freshness_raw.get("stock_oldest_age_days"),
                "threshold_days": freshness_raw.get("threshold_days"),
                "threshold_source": freshness_raw.get("threshold_source"),
            }
        if isinstance(economic_observed_raw, dict):
            economic_observed_compact = {
                "source": economic_observed_raw.get("source"),
                "window": economic_observed_raw.get("window"),
                "anomaly_max_deviation": economic_observed_raw.get(
                    "anomaly_max_deviation"
                ),
                "prices": economic_observed_raw.get("prices"),
                "sample_counts": economic_observed_raw.get("sample_counts"),
            }
        if isinstance(economic_commission_raw, dict):
            economic_commission_compact = {
                "source": economic_commission_raw.get("source"),
                "status": economic_commission_raw.get("status"),
                "reason": economic_commission_raw.get("reason"),
                "commission_percent": economic_commission_raw.get("commission_percent"),
                "commission_percent_stats": economic_commission_raw.get("commission_percent_stats"),
                "kgvp_supplier_percent_stats": economic_commission_raw.get("kgvp_supplier_percent_stats"),
            }

        daily_sales_by_bundle = from_wb_raw.get("daily_sales_by_bundle")
        wb_stock_by_bundle = from_wb_raw.get("wb_stock_by_bundle")
        wb_stock_updated_at_by_bundle = from_wb_raw.get("wb_stock_updated_at_by_bundle")

        compact_meta["from_wb"] = {
            "observation_window_days": from_wb_raw.get("observation_window_days"),
            "freshness_mode": from_wb_raw.get("freshness_mode"),
            "requested_as_of_date": from_wb_raw.get("requested_as_of_date"),
            "as_of_date": from_wb_raw.get("as_of_date"),
            "as_of_source": from_wb_raw.get("as_of_source"),
            "bundle_type_ids": from_wb_raw.get("bundle_type_ids", []),
            "sales_window": from_wb_raw.get("sales_window"),
            "freshness": freshness_compact,
            "economic_observed_prices": economic_observed_compact,
            "economic_observed_commission": economic_commission_compact,
            "snapshot": {
                "daily_sales_bundle_count": (
                    len(daily_sales_by_bundle)
                    if isinstance(daily_sales_by_bundle, dict)
                    else 0
                ),
                "daily_sales_total": _sum_numeric_mapping_values(daily_sales_by_bundle),
                "wb_stock_bundle_count": (
                    len(wb_stock_by_bundle)
                    if isinstance(wb_stock_by_bundle, dict)
                    else 0
                ),
                "wb_stock_total": int(_sum_numeric_mapping_values(wb_stock_by_bundle)),
                "wb_stock_updated_bundle_count": (
                    len(wb_stock_updated_at_by_bundle)
                    if isinstance(wb_stock_updated_at_by_bundle, dict)
                    else 0
                ),
            },
        }

    return compact_meta


def _apply_explainability_mode(
    explanation: ProductionOrderExplanationBlock,
    mode: str,
) -> ProductionOrderExplanationBlock:
    if mode != EXPLAINABILITY_MODE_COMPACT:
        return explanation

    compact_steps, omitted_steps = _compact_explanation_steps(explanation.steps)
    compact_meta = _build_compact_explanation_meta(explanation.meta)
    compact_meta["explainability"] = {
        "mode": EXPLAINABILITY_MODE_COMPACT,
        "steps_omitted": omitted_steps,
    }

    return ProductionOrderExplanationBlock(
        summary=explanation.summary,
        steps=compact_steps,
        meta=compact_meta,
    )


def _load_assorti_bundle_type_flags(
    db: Session,
    bundle_type_ids: list[int],
    admin_assorti_bundle_type_ids: set[int] | None = None,
    global_assorti_bundle_type_ids: set[int] | None = None,
) -> tuple[dict[int, bool], list[dict[str, int | bool | str]]]:
    if not bundle_type_ids:
        return {}, []

    unique_bundle_type_ids = sorted({int(bundle_type_id) for bundle_type_id in bundle_type_ids})

    bundle_types = (
        db.query(BundleType)
        .filter(BundleType.id.in_(unique_bundle_type_ids))
        .all()
    )
    bundle_type_by_id = {int(bundle_type.id): bundle_type for bundle_type in bundle_types}

    admin_assorti_ids = admin_assorti_bundle_type_ids or set()
    global_assorti_ids = global_assorti_bundle_type_ids or set()

    result: dict[int, bool] = {}
    traces: list[dict[str, int | bool | str]] = []

    for bundle_type_id in unique_bundle_type_ids:
        bundle_type = bundle_type_by_id.get(bundle_type_id)
        if bundle_type is not None and bool(bundle_type.is_assorti):
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_SOURCE
        elif bundle_type_id in admin_assorti_ids:
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE
        elif bundle_type_id in global_assorti_ids:
            is_assorti = True
            source = ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE
        elif bundle_type is not None:
            is_assorti = False
            source = ASSORTI_CLASSIFICATION_SOURCE
        else:
            is_assorti = False
            source = ASSORTI_CLASSIFICATION_MISSING_SOURCE

        result[bundle_type_id] = is_assorti
        traces.append(
            {
                "bundle_type_id": int(bundle_type_id),
                "is_assorti": is_assorti,
                "source": source,
            }
        )

    return result, traces


def _build_layer1_stock_health_metrics(
    *,
    bundle_type_ids: list[int],
    demand_by_bundle: dict[int, float],
    recipe_colors_by_bundle: dict[int, set[int]],
    color_to_sizes: dict[int, list[int]],
    size_weights: dict[int, float],
    current_stock_by_color_size: dict[tuple[int, int], int],
    in_flight_effective_by_color_size: dict[tuple[int, int], int],
    in_flight_eta_days_by_color_size: dict[tuple[int, int], int],
    assorti_by_bundle_type: dict[int, bool],
    reorder_point_days: int,
    target_coverage_days: int,
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    unit_capital_per_unit: float,
) -> list[dict[str, int | float | None]]:
    velocity_main_by_color_size: dict[tuple[int, int], float] = defaultdict(float)
    velocity_assorti_by_color_size: dict[tuple[int, int], float] = defaultdict(float)

    for bundle_type_id in bundle_type_ids:
        daily_sales = float(demand_by_bundle.get(bundle_type_id, 0.0))
        if daily_sales <= 0:
            continue

        recipe_colors = sorted(recipe_colors_by_bundle.get(bundle_type_id, set()))
        if not recipe_colors:
            continue

        for color_id in recipe_colors:
            sizes_for_color = color_to_sizes.get(color_id, [])
            if not sizes_for_color:
                continue

            local_size_weights = _normalize_weights(
                sizes_for_color,
                {size_id: size_weights.get(size_id, 0.0) for size_id in sizes_for_color},
            )

            for size_id, weight in local_size_weights.items():
                key = (color_id, size_id)
                velocity = daily_sales * float(weight)
                if assorti_by_bundle_type.get(bundle_type_id, False):
                    velocity_assorti_by_color_size[key] += velocity
                else:
                    velocity_main_by_color_size[key] += velocity

    all_keys = sorted(
        set(current_stock_by_color_size.keys())
        | set(in_flight_effective_by_color_size.keys())
        | set(velocity_main_by_color_size.keys())
        | set(velocity_assorti_by_color_size.keys()),
        key=lambda item: (item[0], item[1]),
    )

    metrics: list[dict[str, int | float | None]] = []
    reorder_point_anchor = max(reorder_point_days, 1)
    overstock_anchor = max(target_coverage_days * 2, 1)
    margin_main = max(float(margin_main_per_unit), 0.0)
    margin_assorti = max(float(margin_assorti_per_unit), 0.0)
    unit_capital = max(float(unit_capital_per_unit), 0.0)

    for color_id, size_id in all_keys:
        key = (color_id, size_id)
        current_stock = max(int(current_stock_by_color_size.get(key, 0)), 0)
        in_flight_effective = max(int(in_flight_effective_by_color_size.get(key, 0)), 0)
        eta_days = in_flight_eta_days_by_color_size.get(key)

        velocity_main = max(float(velocity_main_by_color_size.get(key, 0.0)), 0.0)
        velocity_assorti = max(float(velocity_assorti_by_color_size.get(key, 0.0)), 0.0)
        velocity_total = velocity_main + velocity_assorti

        available_units = current_stock + in_flight_effective
        if velocity_total <= 0:
            coverage_days = 9999.0
            stockout_risk = 0.0
        else:
            coverage_days = float(available_units) / velocity_total
            stockout_risk = max(
                0.0,
                min(
                    (float(reorder_point_anchor) - coverage_days) / float(reorder_point_anchor),
                    1.0,
                ),
            )

        overstock_risk = max(
            0.0,
            min(
                (coverage_days - float(overstock_anchor)) / float(overstock_anchor),
                1.0,
            ),
        )

        if velocity_total > 0:
            gross_margin = (
                (velocity_main * margin_main)
                + (velocity_assorti * margin_assorti)
            ) / velocity_total
        else:
            gross_margin = 0.0

        capital_locked = float(available_units) * unit_capital

        metrics.append(
            {
                "color_id": color_id,
                "size_id": size_id,
                "velocity_main": round(velocity_main, 4),
                "velocity_assorti": round(velocity_assorti, 4),
                "coverage_days": round(coverage_days, 2),
                "current_stock": current_stock,
                "in_flight": in_flight_effective,
                "eta_days": int(eta_days) if eta_days is not None else None,
                "gross_margin": round(gross_margin, 4),
                "capital_locked": round(capital_locked, 2),
                "stockout_risk": round(stockout_risk, 4),
                "overstock_risk": round(overstock_risk, 4),
            }
        )

    return metrics


def _build_layer1_contract_summary(
    stock_health_metrics: list[dict[str, int | float | None]],
) -> dict[str, str | int | dict[str, bool]]:
    seen_keys: set[tuple[int, int]] = set()
    duplicates_found = False

    risk_bounds_valid = True
    non_negative_quantities = True
    non_negative_velocity = True
    non_negative_coverage = True

    for metric in stock_health_metrics:
        color_id_raw = metric.get("color_id")
        size_id_raw = metric.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            duplicates_found = True
            continue

        if line_key in seen_keys:
            duplicates_found = True
        seen_keys.add(line_key)

        stockout_risk = float(metric.get("stockout_risk", 0.0))
        overstock_risk = float(metric.get("overstock_risk", 0.0))
        if not (0.0 <= stockout_risk <= 1.0 and 0.0 <= overstock_risk <= 1.0):
            risk_bounds_valid = False

        current_stock = int(metric.get("current_stock", 0))
        in_flight = int(metric.get("in_flight", 0))
        capital_locked = float(metric.get("capital_locked", 0.0))
        if current_stock < 0 or in_flight < 0 or capital_locked < 0:
            non_negative_quantities = False

        velocity_main = float(metric.get("velocity_main", 0.0))
        velocity_assorti = float(metric.get("velocity_assorti", 0.0))
        if velocity_main < 0 or velocity_assorti < 0:
            non_negative_velocity = False

        coverage_days = float(metric.get("coverage_days", 0.0))
        if coverage_days < 0:
            non_negative_coverage = False

    checks = {
        "unique_color_size_pairs": not duplicates_found,
        "risk_bounds_valid": risk_bounds_valid,
        "non_negative_quantities": non_negative_quantities,
        "non_negative_velocity": non_negative_velocity,
        "non_negative_coverage": non_negative_coverage,
    }
    return {
        "version": LAYER1_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "sku_count": len(stock_health_metrics),
        "checks": checks,
    }


def _build_layer2_allocation_decisions(
    *,
    stock_health_metrics: list[dict[str, int | float | None]],
    lead_time_days_total: int,
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    unit_capital_per_unit: float,
    capital_cost_rate: float = LAYER2_CAPITAL_COST_RATE,
    stockout_penalty_weight: float = LAYER2_STOCKOUT_PENALTY_WEIGHT,
    overstock_penalty_weight: float = LAYER2_OVERSTOCK_PENALTY_WEIGHT,
) -> tuple[list[dict[str, int | float | str]], dict[str, int]]:
    decisions: list[dict[str, int | float | str]] = []
    summary = {
        "main": 0,
        "assorti": 0,
        "hold": 0,
    }
    margin_main = max(float(margin_main_per_unit), 0.0)
    margin_assorti = max(float(margin_assorti_per_unit), 0.0)
    unit_capital = max(float(unit_capital_per_unit), 0.0)
    capital_cost_rate_value = max(float(capital_cost_rate), 0.0)
    stockout_penalty_weight_value = max(float(stockout_penalty_weight), 0.0)
    overstock_penalty_weight_value = max(float(overstock_penalty_weight), 0.0)
    lead_time_anchor = max(int(lead_time_days_total), 1)

    for metric in stock_health_metrics:
        eta_days_raw = metric.get("eta_days")
        eta_days = int(eta_days_raw) if isinstance(eta_days_raw, int) else lead_time_days_total
        horizon_days = max(eta_days, 1)

        current_stock = max(int(metric.get("current_stock", 0)), 0)
        in_flight = max(int(metric.get("in_flight", 0)), 0)
        available_units = current_stock + in_flight

        velocity_main = max(float(metric.get("velocity_main", 0.0)), 0.0)
        velocity_assorti = max(float(metric.get("velocity_assorti", 0.0)), 0.0)
        stockout_risk = _bounded_unit_float(metric.get("stockout_risk", 0.0))
        overstock_risk = _bounded_unit_float(metric.get("overstock_risk", 0.0))

        units_main_until_eta = min(float(available_units), velocity_main * float(horizon_days))
        units_assorti_until_eta = min(float(available_units), velocity_assorti * float(horizon_days))
        demand_main_until_eta = velocity_main * float(horizon_days)
        demand_assorti_until_eta = velocity_assorti * float(horizon_days)

        profit_if_main_until_eta_raw = units_main_until_eta * margin_main
        profit_if_assorti_until_eta_raw = units_assorti_until_eta * margin_assorti

        expected_lost_margin_main_if_stockout = (
            max(demand_main_until_eta - units_main_until_eta, 0.0) * margin_main
        )
        expected_lost_margin_assorti_if_stockout = (
            max(demand_assorti_until_eta - units_assorti_until_eta, 0.0) * margin_assorti
        )
        inventory_carrying_cost_main = max(float(available_units) - units_main_until_eta, 0.0) * unit_capital
        inventory_carrying_cost_assorti = (
            max(float(available_units) - units_assorti_until_eta, 0.0) * unit_capital
        )
        capital_locked_if_main_until_eta = max(units_main_until_eta * unit_capital, 0.0)
        capital_locked_if_assorti_until_eta = max(units_assorti_until_eta * unit_capital, 0.0)
        horizon_factor = float(horizon_days) / float(lead_time_anchor)

        objective_main_components = _compute_objective_components(
            expected_gross_profit=profit_if_main_until_eta_raw,
            capital_locked=capital_locked_if_main_until_eta,
            stockout_risk=stockout_risk,
            overstock_risk=overstock_risk,
            expected_lost_margin_if_stockout=expected_lost_margin_main_if_stockout,
            inventory_carrying_cost=inventory_carrying_cost_main,
            capital_cost_rate=capital_cost_rate_value,
            stockout_penalty_weight=stockout_penalty_weight_value,
            overstock_penalty_weight=overstock_penalty_weight_value,
            horizon_factor=horizon_factor,
        )
        objective_assorti_components = _compute_objective_components(
            expected_gross_profit=profit_if_assorti_until_eta_raw,
            capital_locked=capital_locked_if_assorti_until_eta,
            stockout_risk=stockout_risk,
            overstock_risk=overstock_risk,
            expected_lost_margin_if_stockout=expected_lost_margin_assorti_if_stockout,
            inventory_carrying_cost=inventory_carrying_cost_assorti,
            capital_cost_rate=capital_cost_rate_value,
            stockout_penalty_weight=stockout_penalty_weight_value,
            overstock_penalty_weight=overstock_penalty_weight_value,
            horizon_factor=horizon_factor,
        )

        capital_locked = max(float(metric.get("capital_locked", 0.0)), 0.0)
        if capital_locked <= 0 and unit_capital > 0:
            capital_locked = round(float(available_units) * unit_capital, 4)
        if capital_locked > 0:
            gmroi_main_raw = profit_if_main_until_eta_raw / capital_locked
            gmroi_assorti_raw = profit_if_assorti_until_eta_raw / capital_locked
        else:
            gmroi_main_raw = 0.0
            gmroi_assorti_raw = 0.0

        profit_if_main_until_eta = round(profit_if_main_until_eta_raw, 4)
        profit_if_assorti_until_eta = round(profit_if_assorti_until_eta_raw, 4)
        gmroi_main = round(gmroi_main_raw, 4)
        gmroi_assorti = round(gmroi_assorti_raw, 4)
        objective_score_if_main_until_eta = round(
            objective_main_components["objective_score"],
            4,
        )
        objective_score_if_assorti_until_eta = round(
            objective_assorti_components["objective_score"],
            4,
        )

        profit_gap_until_eta = round(
            abs(profit_if_main_until_eta - profit_if_assorti_until_eta),
            4,
        )
        expected_gross_profit_if_main_until_eta = profit_if_main_until_eta
        expected_gross_profit_if_assorti_until_eta = profit_if_assorti_until_eta
        expected_gross_profit_gap_until_eta = profit_gap_until_eta
        objective_score_gap_until_eta = round(
            abs(objective_score_if_main_until_eta - objective_score_if_assorti_until_eta),
            4,
        )
        gmroi_gap = round(abs(gmroi_main - gmroi_assorti), 4)

        if objective_score_if_main_until_eta > objective_score_if_assorti_until_eta:
            allocation_decision = "main"
        elif objective_score_if_assorti_until_eta > objective_score_if_main_until_eta:
            allocation_decision = "assorti"
        else:
            allocation_decision = "hold"
        decision_reason = LAYER2_DECISION_REASON_LEGACY_BY_DECISION[allocation_decision]
        decision_reason_expected_gross_profit = LAYER2_DECISION_REASON_CANONICAL_BY_DECISION[
            allocation_decision
        ]
        decision_reason_objective_score = LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION[
            allocation_decision
        ]

        tie_break_applied = objective_score_gap_until_eta <= 1e-9
        near_tie = objective_score_gap_until_eta <= LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD

        summary[allocation_decision] += 1

        decisions.append(
            {
                "color_id": int(metric["color_id"]),
                "size_id": int(metric["size_id"]),
                "eta_days": horizon_days,
                "profit_if_main_until_eta": profit_if_main_until_eta,
                "profit_if_assorti_until_eta": profit_if_assorti_until_eta,
                "profit_gap_until_eta": profit_gap_until_eta,
                "expected_gross_profit_if_main_until_eta": expected_gross_profit_if_main_until_eta,
                "expected_gross_profit_if_assorti_until_eta": expected_gross_profit_if_assorti_until_eta,
                "expected_gross_profit_gap_until_eta": expected_gross_profit_gap_until_eta,
                "objective_score_if_main_until_eta": objective_score_if_main_until_eta,
                "objective_score_if_assorti_until_eta": objective_score_if_assorti_until_eta,
                "objective_components_if_main": {
                    "expected_gross_profit": expected_gross_profit_if_main_until_eta,
                    "capital_cost_penalty": round(
                        objective_main_components["capital_cost_penalty"],
                        4,
                    ),
                    "stockout_penalty": round(
                        objective_main_components["stockout_penalty"],
                        4,
                    ),
                    "overstock_penalty": round(
                        objective_main_components["overstock_penalty"],
                        4,
                    ),
                    "objective_score": objective_score_if_main_until_eta,
                },
                "objective_components_if_assorti": {
                    "expected_gross_profit": expected_gross_profit_if_assorti_until_eta,
                    "capital_cost_penalty": round(
                        objective_assorti_components["capital_cost_penalty"],
                        4,
                    ),
                    "stockout_penalty": round(
                        objective_assorti_components["stockout_penalty"],
                        4,
                    ),
                    "overstock_penalty": round(
                        objective_assorti_components["overstock_penalty"],
                        4,
                    ),
                    "objective_score": objective_score_if_assorti_until_eta,
                },
                "objective_score_gap_until_eta": objective_score_gap_until_eta,
                "capital_locked": round(capital_locked, 4),
                "capital_locked_if_main_until_eta": round(capital_locked_if_main_until_eta, 4),
                "capital_locked_if_assorti_until_eta": round(capital_locked_if_assorti_until_eta, 4),
                "capital_cost_penalty_if_main_until_eta": round(
                    objective_main_components["capital_cost_penalty"],
                    4,
                ),
                "capital_cost_penalty_if_assorti_until_eta": round(
                    objective_assorti_components["capital_cost_penalty"],
                    4,
                ),
                "stockout_penalty_if_main_until_eta": round(
                    objective_main_components["stockout_penalty"],
                    4,
                ),
                "stockout_penalty_if_assorti_until_eta": round(
                    objective_assorti_components["stockout_penalty"],
                    4,
                ),
                "overstock_penalty_if_main_until_eta": round(
                    objective_main_components["overstock_penalty"],
                    4,
                ),
                "overstock_penalty_if_assorti_until_eta": round(
                    objective_assorti_components["overstock_penalty"],
                    4,
                ),
                "stockout_risk": round(stockout_risk, 4),
                "overstock_risk": round(overstock_risk, 4),
                "horizon_factor": round(horizon_factor, 4),
                "capital_cost_rate": round(capital_cost_rate_value, 4),
                "stockout_penalty_weight": round(stockout_penalty_weight_value, 4),
                "overstock_penalty_weight": round(overstock_penalty_weight_value, 4),
                "gmroi_main": gmroi_main,
                "gmroi_assorti": gmroi_assorti,
                "gmroi_gap": gmroi_gap,
                "allocation_decision": allocation_decision,
                "decision_reason": decision_reason,
                "decision_reason_expected_gross_profit": decision_reason_expected_gross_profit,
                "decision_reason_objective_score": decision_reason_objective_score,
                "tie_break_applied": tie_break_applied,
                "near_tie": near_tie,
            }
        )

    return decisions, summary


def _build_layer2_contract_summary(
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    layer2_allocation_summary: dict[str, int],
) -> dict[str, str | int | dict[str, bool] | dict[str, int]]:
    expected_decisions = ("main", "assorti", "hold")
    expected_decision_reasons_by_decision = {
        decision: {
            LAYER2_DECISION_REASON_LEGACY_BY_DECISION[decision],
            LAYER2_DECISION_REASON_CANONICAL_BY_DECISION[decision],
        }
        for decision in expected_decisions
    }

    summary_expected = {
        decision: max(int(layer2_allocation_summary.get(decision, 0)), 0)
        for decision in expected_decisions
    }
    summary_actual = {decision: 0 for decision in expected_decisions}

    seen_keys: set[tuple[int, int]] = set()
    duplicates_found = False
    unknown_decisions_found = False
    non_negative_profit_metrics = True
    non_negative_gmroi_metrics = True
    eta_days_positive = True
    tie_break_hold_when_equal_objective = True
    decision_reason_matches_allocation = True
    decision_reason_expected_gross_profit_matches_allocation = True
    decision_reason_objective_score_matches_allocation = True
    allocation_matches_composite_objective_gate = True
    tie_break_applied_matches_objective_tie = True
    near_tie_matches_objective_gap_threshold = True
    profit_gap_consistent_with_profits = True
    gmroi_gap_consistent_with_gmroi = True
    capital_locked_metric_valid = True
    objective_required_fields_present = True
    objective_score_fields_numeric = True
    objective_components_present = True
    objective_components_numeric = True
    objective_components_consistent_with_scores = True
    objective_components_match_formula = True
    objective_score_gap_consistent_with_objective_scores = True
    required_objective_component_keys = (
        "expected_gross_profit",
        "capital_cost_penalty",
        "stockout_penalty",
        "overstock_penalty",
        "objective_score",
    )

    for decision_item in layer2_allocation_decisions:
        color_id_raw = decision_item.get("color_id")
        size_id_raw = decision_item.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            duplicates_found = True
            line_key = None

        if line_key is not None:
            if line_key in seen_keys:
                duplicates_found = True
            seen_keys.add(line_key)

        allocation_decision = str(decision_item.get("allocation_decision", "")).strip().lower()
        if allocation_decision in summary_actual:
            summary_actual[allocation_decision] += 1
        else:
            unknown_decisions_found = True

        decision_reason = str(decision_item.get("decision_reason", "")).strip()
        expected_decision_reasons = expected_decision_reasons_by_decision.get(allocation_decision)
        if expected_decision_reasons is None or decision_reason not in expected_decision_reasons:
            decision_reason_matches_allocation = False

        decision_reason_expected_gross_profit = str(
            decision_item.get("decision_reason_expected_gross_profit", "")
        ).strip()
        expected_decision_reason_expected_gross_profit = (
            LAYER2_DECISION_REASON_CANONICAL_BY_DECISION.get(allocation_decision)
        )
        if decision_reason_expected_gross_profit:
            if (
                expected_decision_reason_expected_gross_profit is None
                or decision_reason_expected_gross_profit
                != expected_decision_reason_expected_gross_profit
            ):
                decision_reason_expected_gross_profit_matches_allocation = False

        decision_reason_objective_score = str(
            decision_item.get("decision_reason_objective_score", "")
        ).strip()
        expected_decision_reason_objective_score = LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION.get(
            allocation_decision
        )
        if (
            expected_decision_reason_objective_score is None
            or decision_reason_objective_score != expected_decision_reason_objective_score
        ):
            decision_reason_objective_score_matches_allocation = False

        try:
            profit_main_raw = decision_item.get("expected_gross_profit_if_main_until_eta")
            if profit_main_raw is None:
                profit_main_raw = decision_item.get("profit_if_main_until_eta", 0.0)
            profit_assorti_raw = decision_item.get("expected_gross_profit_if_assorti_until_eta")
            if profit_assorti_raw is None:
                profit_assorti_raw = decision_item.get("profit_if_assorti_until_eta", 0.0)
            profit_main = float(profit_main_raw)
            profit_assorti = float(profit_assorti_raw)
        except (TypeError, ValueError):
            non_negative_profit_metrics = False
            tie_break_hold_when_equal_objective = False
            allocation_matches_composite_objective_gate = False
            tie_break_applied_matches_objective_tie = False
            near_tie_matches_objective_gap_threshold = False
            profit_gap_consistent_with_profits = False
        else:
            profit_gap_until_eta_expected = abs(profit_main - profit_assorti)
            if profit_main < 0 or profit_assorti < 0:
                non_negative_profit_metrics = False

            objective_main = 0.0
            objective_assorti = 0.0
            objective_main_raw = decision_item.get("objective_score_if_main_until_eta")
            objective_assorti_raw = decision_item.get("objective_score_if_assorti_until_eta")
            objective_components_main_raw = decision_item.get("objective_components_if_main")
            objective_components_assorti_raw = decision_item.get("objective_components_if_assorti")
            objective_scores_valid = True
            objective_components_valid = True
            objective_components_main_score = 0.0
            objective_components_assorti_score = 0.0
            objective_components_main_values: dict[str, float] = {}
            objective_components_assorti_values: dict[str, float] = {}

            if objective_main_raw is None or objective_assorti_raw is None:
                objective_required_fields_present = False
                objective_score_fields_numeric = False
                objective_scores_valid = False
                allocation_matches_composite_objective_gate = False
                objective_components_consistent_with_scores = False
                objective_score_gap_consistent_with_objective_scores = False

            if not isinstance(objective_components_main_raw, dict) or not isinstance(
                objective_components_assorti_raw,
                dict,
            ):
                objective_required_fields_present = False
                objective_components_present = False
                objective_components_numeric = False
                objective_components_valid = False
                allocation_matches_composite_objective_gate = False
                objective_components_consistent_with_scores = False
                objective_components_match_formula = False
            else:
                for component_key in required_objective_component_keys:
                    if (
                        component_key not in objective_components_main_raw
                        or component_key not in objective_components_assorti_raw
                    ):
                        objective_required_fields_present = False
                        objective_components_present = False
                        objective_components_numeric = False
                        objective_components_valid = False
                        allocation_matches_composite_objective_gate = False
                        objective_components_consistent_with_scores = False
                        objective_components_match_formula = False
                        break

                if objective_components_valid:
                    try:
                        for component_key in required_objective_component_keys:
                            objective_components_main_values[component_key] = float(
                                objective_components_main_raw[component_key]
                            )
                            objective_components_assorti_values[component_key] = float(
                                objective_components_assorti_raw[component_key]
                            )
                        objective_components_main_score = objective_components_main_values[
                            "objective_score"
                        ]
                        objective_components_assorti_score = objective_components_assorti_values[
                            "objective_score"
                        ]
                    except (TypeError, ValueError):
                        objective_components_numeric = False
                        objective_components_valid = False
                        allocation_matches_composite_objective_gate = False
                        objective_components_consistent_with_scores = False
                        objective_components_match_formula = False

            try:
                if objective_scores_valid:
                    objective_main = float(objective_main_raw)
                    objective_assorti = float(objective_assorti_raw)
            except (TypeError, ValueError):
                objective_score_fields_numeric = False
                objective_scores_valid = False
                allocation_matches_composite_objective_gate = False
                objective_components_consistent_with_scores = False
                objective_score_gap_consistent_with_objective_scores = False

            if objective_scores_valid and objective_components_valid:
                if abs(objective_main - objective_components_main_score) > 1e-4:
                    objective_components_consistent_with_scores = False
                if abs(objective_assorti - objective_components_assorti_score) > 1e-4:
                    objective_components_consistent_with_scores = False

            if objective_components_valid:
                objective_components_main_formula_score = (
                    objective_components_main_values["expected_gross_profit"]
                    - objective_components_main_values["capital_cost_penalty"]
                    - objective_components_main_values["stockout_penalty"]
                    - objective_components_main_values["overstock_penalty"]
                )
                objective_components_assorti_formula_score = (
                    objective_components_assorti_values["expected_gross_profit"]
                    - objective_components_assorti_values["capital_cost_penalty"]
                    - objective_components_assorti_values["stockout_penalty"]
                    - objective_components_assorti_values["overstock_penalty"]
                )
                if (
                    abs(
                        objective_components_main_formula_score
                        - objective_components_main_values["objective_score"]
                    )
                    > 1e-4
                ):
                    objective_components_match_formula = False
                    allocation_matches_composite_objective_gate = False
                if (
                    abs(
                        objective_components_assorti_formula_score
                        - objective_components_assorti_values["objective_score"]
                    )
                    > 1e-4
                ):
                    objective_components_match_formula = False
                    allocation_matches_composite_objective_gate = False

            if not objective_scores_valid:
                tie_break_hold_when_equal_objective = False
                tie_break_applied_matches_objective_tie = False
                near_tie_matches_objective_gap_threshold = False
                objective_score_gap_consistent_with_objective_scores = False
            else:
                objective_gap_until_eta_expected = abs(objective_main - objective_assorti)
                if objective_main > objective_assorti:
                    expected_allocation_decision = "main"
                elif objective_assorti > objective_main:
                    expected_allocation_decision = "assorti"
                else:
                    expected_allocation_decision = "hold"

                if allocation_decision != expected_allocation_decision:
                    allocation_matches_composite_objective_gate = False

                if objective_gap_until_eta_expected <= 1e-9 and allocation_decision != "hold":
                    tie_break_hold_when_equal_objective = False

                tie_break_applied_raw = decision_item.get("tie_break_applied")
                tie_expected = objective_gap_until_eta_expected <= 1e-9
                if not isinstance(tie_break_applied_raw, bool) or tie_break_applied_raw != tie_expected:
                    tie_break_applied_matches_objective_tie = False

                near_tie_raw = decision_item.get("near_tie")
                near_tie_expected = (
                    objective_gap_until_eta_expected <= LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
                )
                if not isinstance(near_tie_raw, bool) or near_tie_raw != near_tie_expected:
                    near_tie_matches_objective_gap_threshold = False

                try:
                    objective_gap_reported = float(decision_item.get("objective_score_gap_until_eta"))
                except (TypeError, ValueError):
                    objective_score_gap_consistent_with_objective_scores = False
                else:
                    if abs(objective_gap_reported - objective_gap_until_eta_expected) > 1e-4:
                        objective_score_gap_consistent_with_objective_scores = False

            try:
                profit_gap_reported_raw = decision_item.get("expected_gross_profit_gap_until_eta")
                if profit_gap_reported_raw is None:
                    profit_gap_reported_raw = decision_item.get("profit_gap_until_eta")
                profit_gap_reported = float(profit_gap_reported_raw)
            except (TypeError, ValueError):
                profit_gap_consistent_with_profits = False
            else:
                if abs(profit_gap_reported - profit_gap_until_eta_expected) > 1e-4:
                    profit_gap_consistent_with_profits = False

        try:
            gmroi_main = float(decision_item.get("gmroi_main", 0.0))
            gmroi_assorti = float(decision_item.get("gmroi_assorti", 0.0))
        except (TypeError, ValueError):
            non_negative_gmroi_metrics = False
            gmroi_gap_consistent_with_gmroi = False
        else:
            if gmroi_main < 0 or gmroi_assorti < 0:
                non_negative_gmroi_metrics = False

            gmroi_gap_expected = abs(gmroi_main - gmroi_assorti)
            try:
                gmroi_gap_reported = float(decision_item.get("gmroi_gap"))
            except (TypeError, ValueError):
                gmroi_gap_consistent_with_gmroi = False
            else:
                if abs(gmroi_gap_reported - gmroi_gap_expected) > 1e-4:
                    gmroi_gap_consistent_with_gmroi = False

        try:
            capital_locked = float(decision_item.get("capital_locked"))
        except (TypeError, ValueError):
            capital_locked_metric_valid = False
        else:
            if capital_locked < 0:
                capital_locked_metric_valid = False

        try:
            eta_days = int(decision_item.get("eta_days", 0))
        except (TypeError, ValueError):
            eta_days_positive = False
        else:
            if eta_days < 1:
                eta_days_positive = False

    checks = {
        "summary_matches_decisions": summary_actual == summary_expected,
        "summary_total_matches_decision_count": (
            sum(summary_expected.values()) == len(layer2_allocation_decisions)
        ),
        "valid_decisions_only": not unknown_decisions_found,
        "unique_color_size_pairs": not duplicates_found,
        "non_negative_profit_metrics": non_negative_profit_metrics,
        "non_negative_gmroi_metrics": non_negative_gmroi_metrics,
        "eta_days_positive": eta_days_positive,
        "tie_break_hold_when_equal_objective": tie_break_hold_when_equal_objective,
        "tie_break_hold_when_equal_profit": tie_break_hold_when_equal_objective,
        "decision_reason_matches_allocation": decision_reason_matches_allocation,
        "decision_reason_expected_gross_profit_matches_allocation": (
            decision_reason_expected_gross_profit_matches_allocation
        ),
        "decision_reason_objective_score_matches_allocation": (
            decision_reason_objective_score_matches_allocation
        ),
        "allocation_matches_composite_objective_gate": allocation_matches_composite_objective_gate,
        "allocation_matches_profit_gate": allocation_matches_composite_objective_gate,
        "allocation_matches_expected_gross_profit_gate": allocation_matches_composite_objective_gate,
        "tie_break_applied_matches_objective_tie": tie_break_applied_matches_objective_tie,
        "tie_break_applied_matches_profit_tie": tie_break_applied_matches_objective_tie,
        "near_tie_matches_objective_gap_threshold": near_tie_matches_objective_gap_threshold,
        "near_tie_matches_profit_gap_threshold": near_tie_matches_objective_gap_threshold,
        "profit_gap_consistent_with_profits": profit_gap_consistent_with_profits,
        "expected_gross_profit_gap_consistent_with_expected_gross_profits": (
            profit_gap_consistent_with_profits
        ),
        "gmroi_gap_consistent_with_gmroi": gmroi_gap_consistent_with_gmroi,
        "capital_locked_metric_valid": capital_locked_metric_valid,
        "objective_required_fields_present": objective_required_fields_present,
        "objective_score_fields_numeric": objective_score_fields_numeric,
        "objective_components_present": objective_components_present,
        "objective_components_numeric": objective_components_numeric,
        "objective_components_consistent_with_scores": objective_components_consistent_with_scores,
        "objective_components_match_formula": objective_components_match_formula,
        "objective_score_gap_consistent_with_objective_scores": (
            objective_score_gap_consistent_with_objective_scores
        ),
    }
    return {
        "version": LAYER2_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "decision_count": len(layer2_allocation_decisions),
        "summary_expected": summary_expected,
        "summary_actual": summary_actual,
        "checks": checks,
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


def _build_layer2_decision_quality_summary(
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    near_tie_objective_gap_threshold: float = LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD,
    near_tie_profit_gap_threshold: float | None = None,
) -> dict[str, object]:
    resolved_near_tie_objective_gap_threshold = float(near_tie_objective_gap_threshold)
    if near_tie_profit_gap_threshold is not None:
        resolved_near_tie_objective_gap_threshold = float(near_tie_profit_gap_threshold)

    tie_count = 0
    near_tie_count = 0
    total_profit_gap = 0.0
    total_objective_gap = 0.0
    total_gmroi_gap = 0.0
    total_capital_locked = 0.0
    total_objective_score_main = 0.0
    total_objective_score_assorti = 0.0
    objective_fields_valid_count = 0
    objective_fields_missing_count = 0
    objective_fields_invalid_count = 0

    decision_reason_counts = {
        LAYER2_DECISION_REASON_LEGACY_BY_DECISION["main"]: 0,
        LAYER2_DECISION_REASON_LEGACY_BY_DECISION["assorti"]: 0,
        LAYER2_DECISION_REASON_LEGACY_BY_DECISION["hold"]: 0,
    }
    decision_reason_counts_expected_gross_profit = {
        LAYER2_DECISION_REASON_CANONICAL_BY_DECISION["main"]: 0,
        LAYER2_DECISION_REASON_CANONICAL_BY_DECISION["assorti"]: 0,
        LAYER2_DECISION_REASON_CANONICAL_BY_DECISION["hold"]: 0,
    }
    decision_reason_counts_objective_score = {
        LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION["main"]: 0,
        LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION["assorti"]: 0,
        LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION["hold"]: 0,
    }
    canonical_reason_by_legacy_reason = {
        legacy_reason: LAYER2_DECISION_REASON_CANONICAL_BY_DECISION[decision]
        for decision, legacy_reason in LAYER2_DECISION_REASON_LEGACY_BY_DECISION.items()
    }
    objective_reason_by_legacy_reason = {
        legacy_reason: LAYER2_DECISION_REASON_OBJECTIVE_BY_DECISION[decision]
        for decision, legacy_reason in LAYER2_DECISION_REASON_LEGACY_BY_DECISION.items()
    }

    for decision_item in layer2_allocation_decisions:
        try:
            profit_main_raw = decision_item.get("expected_gross_profit_if_main_until_eta")
            if profit_main_raw is None:
                profit_main_raw = decision_item.get("profit_if_main_until_eta", 0.0)
            profit_assorti_raw = decision_item.get("expected_gross_profit_if_assorti_until_eta")
            if profit_assorti_raw is None:
                profit_assorti_raw = decision_item.get("profit_if_assorti_until_eta", 0.0)
            profit_main = float(profit_main_raw)
            profit_assorti = float(profit_assorti_raw)
        except (TypeError, ValueError):
            profit_main = 0.0
            profit_assorti = 0.0

        objective_main_raw = decision_item.get("objective_score_if_main_until_eta")
        objective_assorti_raw = decision_item.get("objective_score_if_assorti_until_eta")
        if objective_main_raw is None or objective_assorti_raw is None:
            objective_fields_missing_count += 1
            objective_main = 0.0
            objective_assorti = 0.0
        else:
            try:
                objective_main = float(objective_main_raw)
                objective_assorti = float(objective_assorti_raw)
            except (TypeError, ValueError):
                objective_fields_invalid_count += 1
                objective_main = 0.0
                objective_assorti = 0.0
            else:
                objective_fields_valid_count += 1

        try:
            gmroi_main = float(decision_item.get("gmroi_main", 0.0))
            gmroi_assorti = float(decision_item.get("gmroi_assorti", 0.0))
        except (TypeError, ValueError):
            gmroi_main = 0.0
            gmroi_assorti = 0.0

        try:
            capital_locked = float(decision_item.get("capital_locked", 0.0))
        except (TypeError, ValueError):
            capital_locked = 0.0

        profit_gap = abs(profit_main - profit_assorti)
        objective_gap = abs(objective_main - objective_assorti)
        gmroi_gap = abs(gmroi_main - gmroi_assorti)
        total_profit_gap += profit_gap
        total_objective_gap += objective_gap
        total_gmroi_gap += gmroi_gap
        total_capital_locked += max(capital_locked, 0.0)
        total_objective_score_main += objective_main
        total_objective_score_assorti += objective_assorti

        tie_break_applied_raw = decision_item.get("tie_break_applied")
        tie_break_applied = (
            tie_break_applied_raw
            if isinstance(tie_break_applied_raw, bool)
            else objective_gap <= 1e-9
        )
        near_tie_raw = decision_item.get("near_tie")
        near_tie = (
            near_tie_raw
            if isinstance(near_tie_raw, bool)
            else objective_gap <= resolved_near_tie_objective_gap_threshold
        )
        if tie_break_applied:
            tie_count += 1
        if near_tie:
            near_tie_count += 1

        decision_reason = str(decision_item.get("decision_reason", "")).strip()
        if decision_reason in decision_reason_counts:
            decision_reason_counts[decision_reason] += 1
        decision_reason_expected_gross_profit = str(
            decision_item.get("decision_reason_expected_gross_profit", "")
        ).strip()
        if decision_reason_expected_gross_profit in decision_reason_counts_expected_gross_profit:
            decision_reason_counts_expected_gross_profit[decision_reason_expected_gross_profit] += 1
        else:
            fallback_canonical_reason = canonical_reason_by_legacy_reason.get(decision_reason)
            if fallback_canonical_reason is not None:
                decision_reason_counts_expected_gross_profit[fallback_canonical_reason] += 1

        decision_reason_objective_score = str(
            decision_item.get("decision_reason_objective_score", "")
        ).strip()
        if decision_reason_objective_score in decision_reason_counts_objective_score:
            decision_reason_counts_objective_score[decision_reason_objective_score] += 1
        else:
            fallback_objective_reason = objective_reason_by_legacy_reason.get(decision_reason)
            if fallback_objective_reason is not None:
                decision_reason_counts_objective_score[fallback_objective_reason] += 1

    decision_count = len(layer2_allocation_decisions)
    divisor = max(decision_count, 1)
    avg_profit_gap_until_eta = round(total_profit_gap / float(divisor), 4)
    return {
        "primary_gate": LAYER2_DECISION_GATE_CANONICAL,
        "composite_objective_gate_primary": True,
        "legacy_gate_primary_aliases": {
            "profit_gate_primary": {
                "value": False,
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
            "expected_gross_profit_gate_primary": {
                "value": False,
                "deprecated_after": LAYER2_LEGACY_GATE_ALIAS_DEPRECATION_WINDOW,
            },
        },
        "legacy_alias_deprecation_plan": _build_layer2_legacy_alias_deprecation_plan(),
        "profit_gate_primary": False,
        "expected_gross_profit_gate_primary": False,
        "gmroi_usage": "diagnostic_only",
        "decision_gate": LAYER2_DECISION_GATE_CANONICAL,
        "decision_gate_canonical": LAYER2_DECISION_GATE_CANONICAL,
        "legacy_decision_gate": LAYER2_DECISION_GATE_LEGACY,
        "near_tie_objective_gap_threshold": round(resolved_near_tie_objective_gap_threshold, 4),
        "near_tie_profit_gap_threshold": round(resolved_near_tie_objective_gap_threshold, 4),
        "decision_count": decision_count,
        "tie_count": tie_count,
        "near_tie_count": near_tie_count,
        "decision_reason_counts": decision_reason_counts,
        "decision_reason_counts_expected_gross_profit": (
            decision_reason_counts_expected_gross_profit
        ),
        "decision_reason_counts_objective_score": decision_reason_counts_objective_score,
        "avg_profit_gap_until_eta": avg_profit_gap_until_eta,
        "avg_expected_gross_profit_gap_until_eta": avg_profit_gap_until_eta,
        "avg_objective_score_gap_until_eta": round(total_objective_gap / float(divisor), 4),
        "avg_gmroi_gap": round(total_gmroi_gap / float(divisor), 4),
        "capital_locked_total": round(total_capital_locked, 4),
        "capital_locked_avg": round(total_capital_locked / float(divisor), 4),
        "objective_score_main_total": round(total_objective_score_main, 4),
        "objective_score_assorti_total": round(total_objective_score_assorti, 4),
        "objective_fields_valid_count": objective_fields_valid_count,
        "objective_fields_missing_count": objective_fields_missing_count,
        "objective_fields_invalid_count": objective_fields_invalid_count,
    }


def _apply_layer3_purchase_shaping(
    *,
    line_qty: dict[tuple[int, int], int],
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    layer3_stockout_boost_max: float = LAYER3_STOCKOUT_BOOST_MAX,
    layer3_overstock_dampen_max: float = LAYER3_OVERSTOCK_DAMPEN_MAX,
) -> tuple[dict[tuple[int, int], str], dict[str, int | float | dict[str, object] | str]]:
    def _bounded_risk(value: object) -> float:
        try:
            risk = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(min(risk, 1.0), 0.0)

    def _calibrated_factor(decision_text: str, stockout_risk: float, overstock_risk: float) -> float:
        base_factor = LAYER3_PURCHASE_FACTOR_BY_DECISION[decision_text]
        stockout_weight = LAYER3_STOCKOUT_WEIGHT_BY_DECISION.get(decision_text, 1.0)
        overstock_weight = LAYER3_OVERSTOCK_WEIGHT_BY_DECISION.get(decision_text, 1.0)

        calibrated = (
            base_factor
            + (stockout_risk * layer3_stockout_boost_max * stockout_weight)
            - (overstock_risk * layer3_overstock_dampen_max * overstock_weight)
        )

        min_factor, max_factor = LAYER3_FACTOR_BOUNDS[decision_text]
        return max(min(calibrated, max_factor), min_factor)

    stock_health_by_line: dict[tuple[int, int], tuple[float, float]] = {}
    for metric in layer1_stock_health_metrics:
        color_id_raw = metric.get("color_id")
        size_id_raw = metric.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            continue

        stock_health_by_line[line_key] = (
            _bounded_risk(metric.get("stockout_risk")),
            _bounded_risk(metric.get("overstock_risk")),
        )

    decision_by_line: dict[tuple[int, int], str] = {}

    for decision in layer2_allocation_decisions:
        color_id_raw = decision.get("color_id")
        size_id_raw = decision.get("size_id")
        try:
            line_key = (int(color_id_raw), int(size_id_raw))
        except (TypeError, ValueError):
            continue

        decision_text = str(decision.get("allocation_decision", "main")).strip().lower()
        if decision_text not in LAYER3_PURCHASE_FACTOR_BY_DECISION:
            decision_text = "main"
        decision_by_line[line_key] = decision_text

    qty_before = sum(max(int(qty), 0) for qty in line_qty.values())
    qty_after_base = 0
    adjusted_lines = 0
    decision_line_counts = {
        "main": 0,
        "assorti": 0,
        "hold": 0,
    }
    calibration_up_lines = 0
    calibration_down_lines = 0
    risk_lines_covered = 0
    risk_lines_missing = 0
    calibrated_factor_sum = 0.0
    calibrated_factor_min: float | None = None
    calibrated_factor_max: float | None = None

    for line_key in sorted(line_qty.keys()):
        current_qty = max(int(line_qty.get(line_key, 0)), 0)
        if current_qty <= 0:
            continue

        decision_text = decision_by_line.get(line_key, "main")
        if decision_text not in LAYER3_PURCHASE_FACTOR_BY_DECISION:
            decision_text = "main"

        decision_line_counts[decision_text] += 1

        base_factor = LAYER3_PURCHASE_FACTOR_BY_DECISION[decision_text]
        base_shaped_qty = floor(float(current_qty) * base_factor)
        if decision_text == "main" and current_qty > 0 and base_shaped_qty <= 0:
            base_shaped_qty = 1
        qty_after_base += max(int(base_shaped_qty), 0)

        stock_health = stock_health_by_line.get(line_key)
        if stock_health is None:
            stockout_risk = 0.0
            overstock_risk = 0.0
            risk_lines_missing += 1
        else:
            stockout_risk, overstock_risk = stock_health
            risk_lines_covered += 1

        factor = _calibrated_factor(
            decision_text=decision_text,
            stockout_risk=stockout_risk,
            overstock_risk=overstock_risk,
        )

        calibrated_factor_sum += factor
        calibrated_factor_min = factor if calibrated_factor_min is None else min(calibrated_factor_min, factor)
        calibrated_factor_max = factor if calibrated_factor_max is None else max(calibrated_factor_max, factor)

        shaped_qty = floor(float(current_qty) * factor)
        if decision_text == "main" and current_qty > 0 and shaped_qty <= 0:
            shaped_qty = 1
        shaped_qty = max(int(shaped_qty), 0)

        if shaped_qty > base_shaped_qty:
            calibration_up_lines += 1
        elif shaped_qty < base_shaped_qty:
            calibration_down_lines += 1

        if shaped_qty != current_qty:
            adjusted_lines += 1

        line_qty[line_key] = shaped_qty

    qty_after = sum(max(int(qty), 0) for qty in line_qty.values())
    calibrated_lines = sum(decision_line_counts.values())
    factor_bounds = {
        decision_text: {
            "min": bounds[0],
            "max": bounds[1],
        }
        for decision_text, bounds in LAYER3_FACTOR_BOUNDS.items()
    }

    return (
        decision_by_line,
        {
            "qty_before": qty_before,
            "qty_after_base": qty_after_base,
            "qty_after": qty_after,
            "qty_delta_vs_base": qty_after - qty_after_base,
            "adjusted_lines": adjusted_lines,
            "main_lines": decision_line_counts["main"],
            "assorti_lines": decision_line_counts["assorti"],
            "hold_lines": decision_line_counts["hold"],
            "calibration_up_lines": calibration_up_lines,
            "calibration_down_lines": calibration_down_lines,
            "calibration": {
                "method": LAYER3_CALIBRATION_METHOD,
                "stockout_boost_max": round(layer3_stockout_boost_max, 4),
                "overstock_dampen_max": round(layer3_overstock_dampen_max, 4),
                "stockout_weight_by_decision": dict(LAYER3_STOCKOUT_WEIGHT_BY_DECISION),
                "overstock_weight_by_decision": dict(LAYER3_OVERSTOCK_WEIGHT_BY_DECISION),
                "factor_bounds": factor_bounds,
                "risk_lines_covered": risk_lines_covered,
                "risk_lines_missing": risk_lines_missing,
                "up_lines": calibration_up_lines,
                "down_lines": calibration_down_lines,
                "factor_summary": {
                    "avg": round(
                        calibrated_factor_sum / float(calibrated_lines),
                        4,
                    )
                    if calibrated_lines > 0
                    else 0.0,
                    "min": round(calibrated_factor_min, 4)
                    if calibrated_factor_min is not None
                    else 0.0,
                    "max": round(calibrated_factor_max, 4)
                    if calibrated_factor_max is not None
                    else 0.0,
                },
            },
        },
    )


def _build_layer3_contract_summary(
    layer3_purchase_shaping: dict[str, object],
) -> dict[str, str | int | dict[str, bool]]:
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _safe_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    qty_before = _safe_int(layer3_purchase_shaping.get("qty_before"))
    qty_after_base = _safe_int(layer3_purchase_shaping.get("qty_after_base"))
    qty_after = _safe_int(layer3_purchase_shaping.get("qty_after"))
    qty_delta_vs_base = _safe_int(layer3_purchase_shaping.get("qty_delta_vs_base"))
    adjusted_lines = _safe_int(layer3_purchase_shaping.get("adjusted_lines"))

    main_lines = _safe_int(layer3_purchase_shaping.get("main_lines"))
    assorti_lines = _safe_int(layer3_purchase_shaping.get("assorti_lines"))
    hold_lines = _safe_int(layer3_purchase_shaping.get("hold_lines"))
    decision_lines_total = main_lines + assorti_lines + hold_lines

    calibration_raw = layer3_purchase_shaping.get("calibration")
    calibration = calibration_raw if isinstance(calibration_raw, dict) else {}

    risk_lines_covered = _safe_int(calibration.get("risk_lines_covered"))
    risk_lines_missing = _safe_int(calibration.get("risk_lines_missing"))
    calibration_up_lines = _safe_int(calibration.get("up_lines"))
    calibration_down_lines = _safe_int(calibration.get("down_lines"))
    calibration_method = str(calibration.get("method", ""))

    factor_bounds_raw = calibration.get("factor_bounds")
    factor_bounds_actual = factor_bounds_raw if isinstance(factor_bounds_raw, dict) else {}
    factor_bounds_expected = {
        decision: {
            "min": bounds[0],
            "max": bounds[1],
        }
        for decision, bounds in LAYER3_FACTOR_BOUNDS.items()
    }

    factor_summary_raw = calibration.get("factor_summary")
    factor_summary = factor_summary_raw if isinstance(factor_summary_raw, dict) else {}
    factor_summary_avg = _safe_float(factor_summary.get("avg"))
    factor_summary_min = _safe_float(factor_summary.get("min"))
    factor_summary_max = _safe_float(factor_summary.get("max"))

    global_factor_min = min(bounds[0] for bounds in LAYER3_FACTOR_BOUNDS.values())
    global_factor_max = max(bounds[1] for bounds in LAYER3_FACTOR_BOUNDS.values())

    checks = {
        "non_negative_quantities": (
            qty_before >= 0 and qty_after_base >= 0 and qty_after >= 0
        ),
        "qty_delta_matches_after_minus_base": (
            qty_delta_vs_base == (qty_after - qty_after_base)
        ),
        "non_negative_line_counts": (
            adjusted_lines >= 0 and main_lines >= 0 and assorti_lines >= 0 and hold_lines >= 0
        ),
        "adjusted_lines_within_decision_lines": adjusted_lines <= decision_lines_total,
        "non_negative_risk_line_counts": (
            risk_lines_covered >= 0 and risk_lines_missing >= 0
        ),
        "risk_partition_matches_decision_lines": (
            risk_lines_covered + risk_lines_missing == decision_lines_total
        ),
        "non_negative_calibration_direction_counts": (
            calibration_up_lines >= 0 and calibration_down_lines >= 0
        ),
        "calibration_direction_counts_within_decision_lines": (
            calibration_up_lines + calibration_down_lines <= decision_lines_total
        ),
        "calibration_method_matches": calibration_method == LAYER3_CALIBRATION_METHOD,
        "factor_bounds_match_expected": factor_bounds_actual == factor_bounds_expected,
        "factor_summary_consistent": (
            factor_summary_min <= factor_summary_avg <= factor_summary_max
        ),
        "factor_summary_within_bounds": (
            decision_lines_total == 0
            and factor_summary_avg == 0.0
            and factor_summary_min == 0.0
            and factor_summary_max == 0.0
        )
        or (
            factor_summary_min >= global_factor_min
            and factor_summary_max <= global_factor_max
        ),
    }
    return {
        "version": LAYER3_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "decision_lines": decision_lines_total,
        "checks": checks,
    }


def _build_layer4_scenarios(
    *,
    base_purchase_units: int,
    available_bundles_for_cover: int,
    total_daily_sales: float,
    reorder_point_days: int,
    expected_horizon_sales: float,
    layer3_purchase_shaping: dict[str, int],
    unit_capital_per_unit: float,
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    average_realized_price_main: float = ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN,
    average_realized_price_assorti: float = ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI,
    capital_cost_rate: float = LAYER2_CAPITAL_COST_RATE,
    stockout_penalty_weight: float = LAYER2_STOCKOUT_PENALTY_WEIGHT,
    overstock_penalty_weight: float = LAYER2_OVERSTOCK_PENALTY_WEIGHT,
) -> list[dict[str, str | int | float]]:
    decision_lines_total = max(
        int(layer3_purchase_shaping.get("main_lines", 0))
        + int(layer3_purchase_shaping.get("assorti_lines", 0))
        + int(layer3_purchase_shaping.get("hold_lines", 0)),
        0,
    )
    assorti_lines = max(int(layer3_purchase_shaping.get("assorti_lines", 0)), 0)
    assorti_share = (
        float(assorti_lines) / float(decision_lines_total)
        if decision_lines_total > 0
        else 0.0
    )

    scenarios: list[dict[str, str | int | float]] = []
    reorder_anchor = max(int(reorder_point_days), 1)
    overstock_anchor = max(reorder_anchor * 2, 1)
    unit_capital = max(float(unit_capital_per_unit), 0.0)
    margin_main = max(float(margin_main_per_unit), 0.0)
    margin_assorti = max(float(margin_assorti_per_unit), 0.0)
    price_main = max(float(average_realized_price_main), 0.0)
    price_assorti = max(float(average_realized_price_assorti), 0.0)
    capital_cost_rate_value = max(float(capital_cost_rate), 0.0)
    stockout_penalty_weight_value = max(float(stockout_penalty_weight), 0.0)
    overstock_penalty_weight_value = max(float(overstock_penalty_weight), 0.0)

    for scenario_name, factor in LAYER4_SCENARIO_FACTORS:
        purchase_units = max(_ceil_to_int(float(base_purchase_units) * factor), 0)
        total_capital_required = round(float(purchase_units) * unit_capital, 2)

        projected_units = max(int(available_bundles_for_cover) + purchase_units, 0)
        if total_daily_sales > 0:
            projected_cover_days = float(projected_units) / float(total_daily_sales)
            stockout_risk_proxy = max(
                0.0,
                min(
                    (float(reorder_anchor) - projected_cover_days) / float(reorder_anchor),
                    1.0,
                ),
            )
            overstock_risk_proxy = max(
                0.0,
                min(
                    (projected_cover_days - float(overstock_anchor)) / float(overstock_anchor),
                    1.0,
                ),
            )
            expected_turnover_proxy = float(expected_horizon_sales) / float(max(projected_units, 1))
        else:
            projected_cover_days = 9999.0
            stockout_risk_proxy = 0.0
            overstock_risk_proxy = 0.0
            expected_turnover_proxy = 0.0

        weighted_price = (price_main * (1.0 - assorti_share)) + (price_assorti * assorti_share)
        weighted_margin = (margin_main * (1.0 - assorti_share)) + (margin_assorti * assorti_share)
        expected_sellable_units = min(float(projected_units), float(max(expected_horizon_sales, 0.0)))
        expected_revenue = expected_sellable_units * weighted_price
        expected_gross_profit = expected_sellable_units * weighted_margin
        expected_margin_percent = (
            (expected_gross_profit / expected_revenue) * 100.0
            if expected_revenue > 0
            else 0.0
        )
        expected_turnover_days = projected_cover_days

        objective_components = _compute_objective_components(
            expected_gross_profit=expected_gross_profit,
            capital_locked=total_capital_required,
            stockout_risk=stockout_risk_proxy,
            overstock_risk=overstock_risk_proxy,
            expected_lost_margin_if_stockout=expected_gross_profit,
            inventory_carrying_cost=total_capital_required,
            capital_cost_rate=capital_cost_rate_value,
            stockout_penalty_weight=stockout_penalty_weight_value,
            overstock_penalty_weight=overstock_penalty_weight_value,
            horizon_factor=1.0,
        )
        risk_adjusted_profit = (
            expected_gross_profit
            - objective_components["stockout_penalty"]
            - objective_components["overstock_penalty"]
        )
        capital_efficiency_metric = (
            expected_gross_profit / total_capital_required
            if total_capital_required > 0
            else 0.0
        )

        if assorti_share <= 0:
            assorti_sustainability_impact = "neutral_no_assorti_signal"
        elif factor < 1.0:
            assorti_sustainability_impact = "negative"
        elif factor > 1.0:
            assorti_sustainability_impact = "positive"
        else:
            assorti_sustainability_impact = "neutral"

        assorti_sustainability_proxy = round(assorti_share * factor, 4)

        scenarios.append(
            {
                "scenario": scenario_name,
                "purchase_units": int(purchase_units),
                "total_capital_required": total_capital_required,
                "expected_revenue": round(expected_revenue, 2),
                "expected_gross_profit": round(expected_gross_profit, 2),
                "expected_margin_percent": round(expected_margin_percent, 2),
                "expected_turnover_days": round(expected_turnover_days, 2),
                "expected_turnover_proxy": round(expected_turnover_proxy, 4),
                "stockout_probability_proxy": round(stockout_risk_proxy, 4),
                "stockout_risk_proxy": round(stockout_risk_proxy, 4),
                "overstock_risk_proxy": round(overstock_risk_proxy, 4),
                "capital_cost_penalty": round(objective_components["capital_cost_penalty"], 2),
                "stockout_penalty": round(objective_components["stockout_penalty"], 2),
                "overstock_penalty": round(objective_components["overstock_penalty"], 2),
                "risk_adjusted_profit": round(risk_adjusted_profit, 2),
                "capital_efficiency_metric": round(capital_efficiency_metric, 6),
                "objective_score": round(objective_components["objective_score"], 2),
                "capital_delta_vs_balanced": 0.0,
                "expected_revenue_delta_vs_balanced": 0.0,
                "expected_gross_profit_delta_vs_balanced": 0.0,
                "gross_profit_delta_vs_balanced": 0.0,
                "objective_score_delta_vs_balanced": 0.0,
                "projected_cover_days": round(projected_cover_days, 2),
                "assorti_sustainability_proxy": assorti_sustainability_proxy,
                "assorti_sustainability_impact": assorti_sustainability_impact,
            }
        )

    balanced = next(
        (
            item
            for item in scenarios
            if str(item.get("scenario", "")).strip().lower() == "balanced"
        ),
        None,
    )
    balanced_capital = float(balanced.get("total_capital_required", 0.0)) if balanced is not None else 0.0
    balanced_revenue = float(balanced.get("expected_revenue", 0.0)) if balanced is not None else 0.0
    balanced_profit = float(balanced.get("expected_gross_profit", 0.0)) if balanced is not None else 0.0
    balanced_objective = float(balanced.get("objective_score", 0.0)) if balanced is not None else 0.0

    for scenario in scenarios:
        capital_value = float(scenario.get("total_capital_required", 0.0))
        revenue_value = float(scenario.get("expected_revenue", 0.0))
        profit_value = float(scenario.get("expected_gross_profit", 0.0))
        objective_value = float(scenario.get("objective_score", 0.0))
        scenario["capital_delta_vs_balanced"] = round(capital_value - balanced_capital, 2)
        scenario["expected_revenue_delta_vs_balanced"] = round(revenue_value - balanced_revenue, 2)
        expected_gross_profit_delta = round(profit_value - balanced_profit, 2)
        scenario["expected_gross_profit_delta_vs_balanced"] = expected_gross_profit_delta
        scenario["gross_profit_delta_vs_balanced"] = expected_gross_profit_delta
        scenario["objective_score_delta_vs_balanced"] = round(objective_value - balanced_objective, 2)

    return scenarios


def _build_line_objective_capital_rankings(
    *,
    candidate_lines: list[ProductionOrderRecommendationLine],
    layer3_decision_by_line: dict[tuple[int, int], str],
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    unit_capital_per_unit: float,
    capital_cost_rate: float,
    stockout_penalty_weight: float,
    overstock_penalty_weight: float,
) -> list[dict[str, int | float | str]]:
    line_risk_by_key: dict[tuple[int, int], tuple[float, float]] = {}
    for metric in layer1_stock_health_metrics:
        try:
            key = (int(metric.get("color_id")), int(metric.get("size_id")))
        except (TypeError, ValueError):
            continue
        line_risk_by_key[key] = (
            _bounded_unit_float(metric.get("stockout_risk", 0.0)),
            _bounded_unit_float(metric.get("overstock_risk", 0.0)),
        )

    unit_capital = max(float(unit_capital_per_unit), 0.0)
    margin_main = max(float(margin_main_per_unit), 0.0)
    margin_assorti = max(float(margin_assorti_per_unit), 0.0)
    rows: list[dict[str, int | float | str]] = []

    for line in candidate_lines:
        requested_qty = max(int(line.recommended_qty), 0)
        if requested_qty <= 0:
            continue

        line_key = (int(line.color_id), int(line.size_id))
        allocation_decision = str(layer3_decision_by_line.get(line_key, "main")).strip().lower()
        if allocation_decision == "assorti":
            margin_per_unit = margin_assorti
        elif allocation_decision == "hold":
            margin_per_unit = min(margin_main, margin_assorti)
        else:
            allocation_decision = "main"
            margin_per_unit = margin_main

        stockout_risk, overstock_risk = line_risk_by_key.get(line_key, (0.0, 0.0))
        capital_required = float(requested_qty) * unit_capital
        expected_gross_profit = float(requested_qty) * margin_per_unit
        objective_components = _compute_objective_components(
            expected_gross_profit=expected_gross_profit,
            capital_locked=capital_required,
            stockout_risk=stockout_risk,
            overstock_risk=overstock_risk,
            expected_lost_margin_if_stockout=expected_gross_profit,
            inventory_carrying_cost=capital_required,
            capital_cost_rate=capital_cost_rate,
            stockout_penalty_weight=stockout_penalty_weight,
            overstock_penalty_weight=overstock_penalty_weight,
            horizon_factor=1.0,
        )
        objective_score = objective_components["objective_score"]
        objective_score_per_capital = (
            objective_score / capital_required
            if capital_required > 0
            else objective_score
        )
        risk_priority_score = stockout_risk - overstock_risk

        rows.append(
            {
                "color_id": int(line.color_id),
                "size_id": int(line.size_id),
                "requested_qty": requested_qty,
                "allocation_decision": allocation_decision,
                "stockout_risk": round(stockout_risk, 4),
                "overstock_risk": round(overstock_risk, 4),
                "capital_required": round(capital_required, 4),
                "expected_gross_profit": round(expected_gross_profit, 4),
                "objective_score": round(objective_score, 4),
                "objective_score_per_capital": round(objective_score_per_capital, 6),
                "risk_priority_score": round(risk_priority_score, 6),
            }
        )

    ranked = sorted(
        rows,
        key=lambda item: (
            -float(item["objective_score_per_capital"]),
            -float(item["objective_score"]),
            -float(item.get("stockout_risk", 0.0)),
            float(item.get("overstock_risk", 0.0)),
            int(item["color_id"]),
            int(item["size_id"]),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def _apply_capital_constraint_to_candidate_lines(
    *,
    candidate_lines: list[ProductionOrderRecommendationLine],
    ranked_line_objectives: list[dict[str, int | float | str]],
    available_capital: float | None,
    unit_capital_per_unit: float,
) -> tuple[list[ProductionOrderRecommendationLine], dict[str, object]]:
    unit_capital = max(float(unit_capital_per_unit), 0.0)
    required_capital_before = round(
        sum(max(int(line.recommended_qty), 0) * unit_capital for line in candidate_lines),
        2,
    )

    if available_capital is None:
        return (
            candidate_lines,
            {
                "status": "available_capital_not_set",
                "constrained": False,
                "available_capital": None,
                "required_capital_before_constraint": required_capital_before,
                "allocated_capital_after_constraint": required_capital_before,
                "remaining_capital": None,
                "line_count_before": len(candidate_lines),
                "line_count_after": len(candidate_lines),
                "cutoff_line": None,
                "ranking": ranked_line_objectives,
            },
        )

    available_capital_value = max(float(available_capital), 0.0)
    if unit_capital <= 0 or required_capital_before <= available_capital_value:
        return (
            candidate_lines,
            {
                "status": "within_budget",
                "constrained": False,
                "available_capital": round(available_capital_value, 2),
                "required_capital_before_constraint": required_capital_before,
                "allocated_capital_after_constraint": required_capital_before,
                "remaining_capital": round(max(available_capital_value - required_capital_before, 0.0), 2),
                "line_count_before": len(candidate_lines),
                "line_count_after": len(candidate_lines),
                "cutoff_line": None,
                "ranking": ranked_line_objectives,
            },
        )

    candidate_line_by_key = {
        (int(line.color_id), int(line.size_id)): line
        for line in candidate_lines
    }
    constrained_lines: list[ProductionOrderRecommendationLine] = []
    remaining_capital = available_capital_value
    allocated_capital = 0.0
    cutoff_line: dict[str, object] | None = None

    for ranked_line in ranked_line_objectives:
        key = (int(ranked_line["color_id"]), int(ranked_line["size_id"]))
        source_line = candidate_line_by_key.get(key)
        if source_line is None:
            continue

        requested_qty = max(int(source_line.recommended_qty), 0)
        if requested_qty <= 0:
            continue

        max_affordable_qty = int(remaining_capital // unit_capital)
        allocated_qty = min(requested_qty, max(max_affordable_qty, 0))

        if allocated_qty <= 0:
            if cutoff_line is None:
                cutoff_line = {
                    "rank": int(ranked_line.get("rank", 0)),
                    "color_id": int(source_line.color_id),
                    "size_id": int(source_line.size_id),
                    "requested_qty": requested_qty,
                    "allocated_qty": 0,
                    "objective_score_per_capital": float(
                        ranked_line.get("objective_score_per_capital", 0.0)
                    ),
                }
            continue

        if allocated_qty < requested_qty and cutoff_line is None:
            cutoff_line = {
                "rank": int(ranked_line.get("rank", 0)),
                "color_id": int(source_line.color_id),
                "size_id": int(source_line.size_id),
                "requested_qty": requested_qty,
                "allocated_qty": allocated_qty,
                "objective_score_per_capital": float(
                    ranked_line.get("objective_score_per_capital", 0.0)
                ),
            }

        constrained_lines.append(
            ProductionOrderRecommendationLine(
                article_id=source_line.article_id,
                color_id=source_line.color_id,
                size_id=source_line.size_id,
                recommended_qty=allocated_qty,
                source_reason=f"{source_line.source_reason}|capital_constraint",
            )
        )

        allocated_capital += float(allocated_qty) * unit_capital
        remaining_capital = max(remaining_capital - (float(allocated_qty) * unit_capital), 0.0)

    return (
        constrained_lines,
        {
            "status": "budget_limited_applied",
            "constrained": True,
            "available_capital": round(available_capital_value, 2),
            "required_capital_before_constraint": required_capital_before,
            "allocated_capital_after_constraint": round(allocated_capital, 2),
            "remaining_capital": round(remaining_capital, 2),
            "line_count_before": len(candidate_lines),
            "line_count_after": len(constrained_lines),
            "cutoff_line": cutoff_line,
            "ranking": ranked_line_objectives,
        },
    )


def _build_capital_constraint_contract_summary(
    capital_constraint_summary: dict[str, object],
) -> dict[str, str | dict[str, bool]]:
    allowed_statuses = {
        "available_capital_not_set",
        "within_budget",
        "budget_limited_applied",
    }
    status = str(capital_constraint_summary.get("status", "")).strip()
    constrained_raw = capital_constraint_summary.get("constrained")

    status_known = status in allowed_statuses
    constrained_is_bool = isinstance(constrained_raw, bool)
    constrained_matches_status = False
    if constrained_is_bool:
        if status == "budget_limited_applied":
            constrained_matches_status = constrained_raw is True
        elif status in {"available_capital_not_set", "within_budget"}:
            constrained_matches_status = constrained_raw is False

    def _to_non_negative_float(value: object) -> tuple[bool, float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False, 0.0
        if number < 0:
            return False, 0.0
        return True, number

    required_ok, required_capital = _to_non_negative_float(
        capital_constraint_summary.get("required_capital_before_constraint")
    )
    allocated_ok, allocated_capital = _to_non_negative_float(
        capital_constraint_summary.get("allocated_capital_after_constraint")
    )

    available_raw = capital_constraint_summary.get("available_capital")
    if status == "available_capital_not_set":
        available_consistent = available_raw is None
        available_ok = True
        available_capital = 0.0
    else:
        available_ok, available_capital = _to_non_negative_float(available_raw)
        available_consistent = available_ok

    remaining_raw = capital_constraint_summary.get("remaining_capital")
    if status == "available_capital_not_set":
        remaining_consistent = remaining_raw is None
        remaining_ok = True
        remaining_capital = 0.0
    else:
        remaining_ok, remaining_capital = _to_non_negative_float(remaining_raw)
        remaining_consistent = remaining_ok

    allocation_not_exceed_required = (
        required_ok and allocated_ok and allocated_capital <= (required_capital + 1e-4)
    )
    allocation_not_exceed_available = (
        status == "available_capital_not_set"
        or (
            available_ok
            and allocated_ok
            and allocated_capital <= (available_capital + 1e-4)
        )
    )
    budget_accounting_consistent = (
        status == "available_capital_not_set"
        or (
            available_ok
            and allocated_ok
            and remaining_ok
            and abs((available_capital - allocated_capital) - remaining_capital) <= 0.05
        )
    )

    line_counts_non_negative = True
    line_count_order_valid = True
    unconstrained_preserves_line_count = True
    line_count_before = 0
    line_count_after = 0
    try:
        line_count_before = int(capital_constraint_summary.get("line_count_before", 0))
        line_count_after = int(capital_constraint_summary.get("line_count_after", 0))
    except (TypeError, ValueError):
        line_counts_non_negative = False
        line_count_order_valid = False
        unconstrained_preserves_line_count = False
    else:
        if line_count_before < 0 or line_count_after < 0:
            line_counts_non_negative = False
        if line_count_after > line_count_before:
            line_count_order_valid = False
        if (
            status in {"available_capital_not_set", "within_budget"}
            and line_count_before != line_count_after
        ):
            unconstrained_preserves_line_count = False

    ranking_is_list = isinstance(capital_constraint_summary.get("ranking"), list)
    ranking_unique_line_keys = True
    ranking_entries_numeric = True
    ranking_sorted_by_objective_per_capital = True
    ranking_risk_priority_consistent = True
    ranking_rows = capital_constraint_summary.get("ranking", [])
    previous_sort_key: tuple[float, float, float, float, int, int] | None = None
    seen_ranking_keys: set[tuple[int, int]] = set()
    if ranking_is_list:
        for ranking_row in ranking_rows:
            if not isinstance(ranking_row, dict):
                ranking_entries_numeric = False
                ranking_sorted_by_objective_per_capital = False
                ranking_risk_priority_consistent = False
                continue
            try:
                color_id = int(ranking_row.get("color_id"))
                size_id = int(ranking_row.get("size_id"))
                objective_score_per_capital = float(
                    ranking_row.get("objective_score_per_capital", 0.0)
                )
                objective_score = float(ranking_row.get("objective_score", 0.0))
                stockout_risk = float(ranking_row.get("stockout_risk", 0.0))
                overstock_risk = float(ranking_row.get("overstock_risk", 0.0))
                risk_priority_score = float(ranking_row.get("risk_priority_score"))
            except (TypeError, ValueError):
                ranking_entries_numeric = False
                ranking_sorted_by_objective_per_capital = False
                ranking_risk_priority_consistent = False
                continue

            line_key = (color_id, size_id)
            if line_key in seen_ranking_keys:
                ranking_unique_line_keys = False
            seen_ranking_keys.add(line_key)

            sort_key = (
                -objective_score_per_capital,
                -objective_score,
                -stockout_risk,
                overstock_risk,
                color_id,
                size_id,
            )
            if previous_sort_key is not None and sort_key < previous_sort_key:
                ranking_sorted_by_objective_per_capital = False
            previous_sort_key = sort_key

            expected_risk_priority_score = stockout_risk - overstock_risk
            if abs(risk_priority_score - expected_risk_priority_score) > 1e-4:
                ranking_risk_priority_consistent = False
    else:
        ranking_unique_line_keys = False
        ranking_entries_numeric = False
        ranking_sorted_by_objective_per_capital = False
        ranking_risk_priority_consistent = False

    cutoff_line = capital_constraint_summary.get("cutoff_line")
    cutoff_line_shape_valid = cutoff_line is None or isinstance(cutoff_line, dict)
    cutoff_line_qty_consistent = True
    cutoff_line_matches_ranking = True
    if isinstance(cutoff_line, dict):
        try:
            cutoff_color_id = int(cutoff_line.get("color_id"))
            cutoff_size_id = int(cutoff_line.get("size_id"))
            cutoff_requested_qty = int(cutoff_line.get("requested_qty", 0))
            cutoff_allocated_qty = int(cutoff_line.get("allocated_qty", 0))
        except (TypeError, ValueError):
            cutoff_line_qty_consistent = False
            cutoff_line_matches_ranking = False
        else:
            if (
                cutoff_requested_qty < 0
                or cutoff_allocated_qty < 0
                or cutoff_allocated_qty > cutoff_requested_qty
            ):
                cutoff_line_qty_consistent = False
            if ranking_is_list:
                cutoff_line_in_ranking = False
                for ranking_row in ranking_rows:
                    if not isinstance(ranking_row, dict):
                        continue
                    try:
                        ranking_color_id = int(ranking_row.get("color_id", -1))
                        ranking_size_id = int(ranking_row.get("size_id", -1))
                    except (TypeError, ValueError):
                        continue
                    if (
                        ranking_color_id == cutoff_color_id
                        and ranking_size_id == cutoff_size_id
                    ):
                        cutoff_line_in_ranking = True
                        break
                if not cutoff_line_in_ranking:
                    cutoff_line_matches_ranking = False

    cutoff_line_present_when_limited = (
        status != "budget_limited_applied"
        or isinstance(cutoff_line, dict)
    )

    checks = {
        "status_known": status_known,
        "constrained_is_bool": constrained_is_bool,
        "constrained_matches_status": constrained_matches_status,
        "required_capital_non_negative": required_ok,
        "allocated_capital_non_negative": allocated_ok,
        "available_capital_consistent": available_consistent,
        "remaining_capital_consistent": remaining_consistent,
        "allocation_not_exceed_required": allocation_not_exceed_required,
        "allocation_not_exceed_available": allocation_not_exceed_available,
        "budget_accounting_consistent": budget_accounting_consistent,
        "line_counts_non_negative": line_counts_non_negative,
        "line_count_order_valid": line_count_order_valid,
        "unconstrained_preserves_line_count": unconstrained_preserves_line_count,
        "ranking_is_list": ranking_is_list,
        "ranking_unique_line_keys": ranking_unique_line_keys,
        "ranking_entries_numeric": ranking_entries_numeric,
        "ranking_sorted_by_objective_per_capital": (
            ranking_sorted_by_objective_per_capital
        ),
        "ranking_risk_priority_consistent": ranking_risk_priority_consistent,
        "cutoff_line_shape_valid": cutoff_line_shape_valid,
        "cutoff_line_qty_consistent": cutoff_line_qty_consistent,
        "cutoff_line_matches_ranking": cutoff_line_matches_ranking,
        "cutoff_line_present_when_limited": cutoff_line_present_when_limited,
    }
    return {
        "version": CAPITAL_CONSTRAINT_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "checks": checks,
    }


def _build_capital_gap_summary(
    *,
    layer4_scenarios: list[dict[str, str | int | float]],
    available_capital: float | None,
) -> dict[str, float | str | None]:
    balanced = next(
        (
            item
            for item in layer4_scenarios
            if str(item.get("scenario", "")).strip().lower() == "balanced"
        ),
        None,
    )
    required_capital = (
        float(balanced.get("total_capital_required", 0.0))
        if balanced is not None
        else 0.0
    )
    if available_capital is None:
        return {
            "status": "available_capital_not_set",
            "available_capital": None,
            "required_capital": round(required_capital, 2),
            "deficit_or_surplus": None,
        }

    deficit_or_surplus = round(float(available_capital) - required_capital, 2)
    return {
        "status": "ok",
        "available_capital": round(float(available_capital), 2),
        "required_capital": round(required_capital, 2),
        "deficit_or_surplus": deficit_or_surplus,
    }


def _build_layer4_contract_summary(
    layer4_scenarios: list[dict[str, str | int | float]],
) -> dict[str, str | bool | list[str] | dict[str, bool]]:
    scenario_order_actual = [
        str(item.get("scenario", ""))
        for item in layer4_scenarios
    ]
    scenario_order_expected = list(LAYER4_SCENARIO_ORDER)
    order_matches_expected = scenario_order_actual == scenario_order_expected

    capitals = [
        float(item.get("total_capital_required", 0.0))
        for item in layer4_scenarios
    ]
    stockout_risks = [
        float(item.get("stockout_risk_proxy", 0.0))
        for item in layer4_scenarios
    ]
    turnover_values = [
        float(item.get("expected_turnover_proxy", 0.0))
        for item in layer4_scenarios
    ]
    purchase_units = [
        int(item.get("purchase_units", 0))
        for item in layer4_scenarios
    ]

    required_delta_fields = (
        "capital_delta_vs_balanced",
        "expected_revenue_delta_vs_balanced",
        "expected_gross_profit_delta_vs_balanced",
        "gross_profit_delta_vs_balanced",
        "objective_score_delta_vs_balanced",
    )
    balanced = next(
        (
            item
            for item in layer4_scenarios
            if str(item.get("scenario", "")).strip().lower() == "balanced"
        ),
        None,
    )
    scenario_delta_fields_present = True
    scenario_deltas_match_balanced = True
    if balanced is None:
        scenario_delta_fields_present = False
        scenario_deltas_match_balanced = False
        balanced_capital = 0.0
        balanced_revenue = 0.0
        balanced_profit = 0.0
        balanced_objective = 0.0
    else:
        balanced_capital = float(balanced.get("total_capital_required", 0.0))
        balanced_revenue = float(balanced.get("expected_revenue", 0.0))
        balanced_profit = float(balanced.get("expected_gross_profit", 0.0))
        balanced_objective = float(balanced.get("objective_score", 0.0))

    for scenario_item in layer4_scenarios:
        if any(field_name not in scenario_item for field_name in required_delta_fields):
            scenario_delta_fields_present = False
            scenario_deltas_match_balanced = False
            continue

        if balanced is None:
            scenario_deltas_match_balanced = False
            continue

        try:
            capital = float(scenario_item.get("total_capital_required", 0.0))
            revenue = float(scenario_item.get("expected_revenue", 0.0))
            profit = float(scenario_item.get("expected_gross_profit", 0.0))
            objective = float(scenario_item.get("objective_score", 0.0))
            capital_delta = float(scenario_item.get("capital_delta_vs_balanced"))
            revenue_delta = float(scenario_item.get("expected_revenue_delta_vs_balanced"))
            profit_delta = float(scenario_item.get("expected_gross_profit_delta_vs_balanced"))
            profit_delta_alias = float(scenario_item.get("gross_profit_delta_vs_balanced"))
            objective_delta = float(scenario_item.get("objective_score_delta_vs_balanced"))
        except (TypeError, ValueError):
            scenario_deltas_match_balanced = False
            continue

        if abs(capital_delta - (capital - balanced_capital)) > 1e-4:
            scenario_deltas_match_balanced = False
        if abs(revenue_delta - (revenue - balanced_revenue)) > 1e-4:
            scenario_deltas_match_balanced = False
        if abs(profit_delta - (profit - balanced_profit)) > 1e-4:
            scenario_deltas_match_balanced = False
        if abs(profit_delta_alias - profit_delta) > 1e-4:
            scenario_deltas_match_balanced = False
        if abs(objective_delta - (objective - balanced_objective)) > 1e-4:
            scenario_deltas_match_balanced = False

    checks = {
        "capital_non_decreasing": all(
            current >= previous
            for previous, current in zip(capitals, capitals[1:])
        ),
        "stockout_risk_non_increasing": all(
            current <= previous
            for previous, current in zip(stockout_risks, stockout_risks[1:])
        ),
        "turnover_non_increasing": all(
            current <= previous
            for previous, current in zip(turnover_values, turnover_values[1:])
        ),
        "purchase_units_non_decreasing": all(
            current >= previous
            for previous, current in zip(purchase_units, purchase_units[1:])
        ),
        "scenario_delta_fields_present": scenario_delta_fields_present,
        "scenario_deltas_match_balanced": scenario_deltas_match_balanced,
    }

    contract_ok = order_matches_expected and all(checks.values())
    return {
        "version": LAYER4_CONTRACT_VERSION,
        "status": "ok" if contract_ok else "violated",
        "order_matches_expected": order_matches_expected,
        "scenario_order_expected": scenario_order_expected,
        "scenario_order_actual": scenario_order_actual,
        "checks": checks,
    }


def _build_layer4_aggregate_deltas(
    layer4_scenarios: list[dict[str, str | int | float]],
) -> dict[str, dict[str, float]]:
    def _scenario(name: str) -> dict[str, str | int | float] | None:
        scenario_key = name.strip().lower()
        return next(
            (
                item
                for item in layer4_scenarios
                if str(item.get("scenario", "")).strip().lower() == scenario_key
            ),
            None,
        )

    conservative = _scenario("conservative")
    aggressive = _scenario("aggressive")

    conservative_capital = float(conservative.get("total_capital_required", 0.0)) if conservative else 0.0
    aggressive_capital = float(aggressive.get("total_capital_required", 0.0)) if aggressive else 0.0
    conservative_revenue = float(conservative.get("expected_revenue", 0.0)) if conservative else 0.0
    aggressive_revenue = float(aggressive.get("expected_revenue", 0.0)) if aggressive else 0.0
    conservative_profit = float(conservative.get("expected_gross_profit", 0.0)) if conservative else 0.0
    aggressive_profit = float(aggressive.get("expected_gross_profit", 0.0)) if aggressive else 0.0
    conservative_objective = float(conservative.get("objective_score", 0.0)) if conservative else 0.0
    aggressive_objective = float(aggressive.get("objective_score", 0.0)) if aggressive else 0.0

    return {
        "aggressive_vs_conservative": {
            "capital_delta": round(aggressive_capital - conservative_capital, 2),
            "expected_revenue_delta": round(aggressive_revenue - conservative_revenue, 2),
            "gross_profit_delta": round(aggressive_profit - conservative_profit, 2),
            "objective_delta": round(aggressive_objective - conservative_objective, 2),
        }
    }


def _build_layer5_intervention_signals(
    *,
    risk_level: str,
    layer4_scenarios: list[dict[str, str | int | float]],
    in_flight_effective_qty_total: int,
    unavoidable_stockout_risk_threshold: float = LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
    accelerate_production_risk_threshold: float = LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    accelerate_action_cost_rate: float = LAYER5_ACCELERATE_ACTION_COST_RATE,
    price_slowdown_lost_volume_rate: float = LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE,
    reduce_order_marginal_profit_rate: float = LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
) -> dict[str, str | bool | float | list[str] | dict[str, float | str]]:
    def _scenario(name: str) -> dict[str, str | int | float] | None:
        scenario_key = name.strip().lower()
        return next(
            (
                item
                for item in layer4_scenarios
                if str(item.get("scenario", "")).strip().lower() == scenario_key
            ),
            None,
        )

    conservative = _scenario("conservative")
    balanced = _scenario("balanced")
    aggressive = _scenario("aggressive")

    aggressive_stockout_risk = _bounded_unit_float(
        aggressive.get("stockout_risk_proxy", 0.0)
        if aggressive is not None
        else 0.0
    )
    aggressive_overstock_risk = _bounded_unit_float(
        aggressive.get("overstock_risk_proxy", 0.0)
        if aggressive is not None
        else 0.0
    )

    unavoidable_stockout = (
        risk_level == "critical"
        and aggressive_stockout_risk >= unavoidable_stockout_risk_threshold
    )

    accelerate_action_cost_rate_value = max(float(accelerate_action_cost_rate), 0.0)
    price_slowdown_lost_volume_rate_value = max(float(price_slowdown_lost_volume_rate), 0.0)
    reduce_order_marginal_profit_rate_value = max(float(reduce_order_marginal_profit_rate), 0.0)

    aggressive_stockout_penalty = max(
        float(aggressive.get("stockout_penalty", aggressive_stockout_risk))
        if aggressive is not None
        else aggressive_stockout_risk,
        0.0,
    )
    aggressive_overstock_penalty = max(
        float(aggressive.get("overstock_penalty", aggressive_overstock_risk))
        if aggressive is not None
        else aggressive_overstock_risk,
        0.0,
    )
    aggressive_capital = max(
        float(aggressive.get("total_capital_required", 0.0))
        if aggressive is not None
        else 0.0,
        0.0,
    )
    aggressive_profit = max(
        float(aggressive.get("expected_gross_profit", 0.0))
        if aggressive is not None
        else 0.0,
        0.0,
    )
    conservative_stockout_penalty = max(
        float(conservative.get("stockout_penalty", 0.0))
        if conservative is not None
        else 0.0,
        0.0,
    )
    conservative_profit = max(
        float(conservative.get("expected_gross_profit", 0.0))
        if conservative is not None
        else 0.0,
        0.0,
    )
    balanced_profit = max(
        float(balanced.get("expected_gross_profit", 0.0))
        if balanced is not None
        else 0.0,
        0.0,
    )

    expected_loss_if_no_action = max(
        aggressive_stockout_penalty,
        aggressive_stockout_risk,
    )
    action_cost = aggressive_capital * accelerate_action_cost_rate_value

    margin_improvement_from_slowdown = max(
        aggressive_stockout_penalty - conservative_stockout_penalty,
        aggressive_stockout_risk,
    )
    lost_volume_cost = max(aggressive_profit - conservative_profit, 0.0) * price_slowdown_lost_volume_rate_value

    overstock_penalty = max(aggressive_overstock_penalty, aggressive_overstock_risk)
    marginal_profit_of_additional_units = max(aggressive_profit - balanced_profit, 0.0)

    signals: list[str] = []
    reason = "none"

    accelerate_condition = (
        unavoidable_stockout
        and aggressive_stockout_risk >= accelerate_production_risk_threshold
        and expected_loss_if_no_action > action_cost
    )
    increase_price_condition = (
        unavoidable_stockout
        and margin_improvement_from_slowdown > lost_volume_cost
    )
    reduce_order_condition = (
        overstock_penalty
        > (marginal_profit_of_additional_units * reduce_order_marginal_profit_rate_value)
        and aggressive_overstock_risk >= max(aggressive_stockout_risk, 0.2)
    )

    if in_flight_effective_qty_total <= 0:
        if accelerate_condition:
            signals.append("accelerate_production")
        elif increase_price_condition:
            signals.append("increase_price_to_slow_velocity")
    else:
        if accelerate_condition:
            signals.append("accelerate_production")
        if increase_price_condition:
            signals.append("increase_price_to_slow_velocity")
    if reduce_order_condition:
        signals.append("reduce_order_size")

    if signals == ["accelerate_production"]:
        reason = (
            "no_effective_in_flight_and_high_stockout_risk"
            if in_flight_effective_qty_total <= 0
            else "in_flight_present_but_severe_stockout_risk"
        )
    elif signals == ["increase_price_to_slow_velocity"]:
        reason = (
            "no_effective_in_flight_but_stockout_risk_persists"
            if in_flight_effective_qty_total <= 0
            else "in_flight_present_but_stockout_risk_persists"
        )
    elif signals == ["accelerate_production", "increase_price_to_slow_velocity"]:
        reason = (
            "no_effective_in_flight_and_high_stockout_risk"
            if in_flight_effective_qty_total <= 0
            else "in_flight_present_but_severe_stockout_risk"
        )
    elif signals == ["reduce_order_size"]:
        reason = "overstock_penalty_exceeds_marginal_profit"
    elif signals:
        reason = "mixed_risk_and_cost_signals"

    return {
        "method": "deterministic_unavoidable_stockout_flags",
        "signal_policy": "critical_risk_thresholds",
        "economic_policy": "cost_aware_thresholds",
        "unavoidable_stockout": unavoidable_stockout,
        "signals": signals,
        "reason": reason,
        "aggressive_stockout_risk_proxy": round(aggressive_stockout_risk, 4),
        "aggressive_overstock_risk_proxy": round(aggressive_overstock_risk, 4),
        "risk_threshold": round(unavoidable_stockout_risk_threshold, 4),
        "signal_thresholds": {
            "accelerate_production": round(accelerate_production_risk_threshold, 4),
            "increase_price_to_slow_velocity": round(unavoidable_stockout_risk_threshold, 4),
            "reduce_order_size": round(reduce_order_marginal_profit_rate_value, 4),
        },
        "economic_justification": {
            "expected_loss_if_no_action": round(expected_loss_if_no_action, 4),
            "action_cost": round(action_cost, 4),
            "margin_improvement_from_slowdown": round(margin_improvement_from_slowdown, 4),
            "lost_volume_cost": round(lost_volume_cost, 4),
            "overstock_penalty": round(overstock_penalty, 4),
            "marginal_profit_of_additional_units": round(marginal_profit_of_additional_units, 4),
            "formulas": {
                "accelerate_production": "expected_loss_if_no_action > action_cost",
                "increase_price_to_slow_velocity": "margin_improvement_from_slowdown > lost_volume_cost",
                "reduce_order_size": "overstock_penalty > marginal_profit_of_additional_units",
            },
        },
    }


def _build_layer5_contract_summary(
    *,
    layer5_intervention: dict[str, object],
    unavoidable_stockout_risk_threshold: float,
    accelerate_production_risk_threshold: float,
    reduce_order_marginal_profit_rate: float = LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
) -> dict[str, str | int | dict[str, bool]]:
    def _safe_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    method = str(layer5_intervention.get("method", ""))
    signal_policy = str(layer5_intervention.get("signal_policy", ""))
    economic_policy = str(layer5_intervention.get("economic_policy", ""))
    reason = str(layer5_intervention.get("reason", ""))

    unavoidable_raw = layer5_intervention.get("unavoidable_stockout")
    unavoidable_stockout_is_bool = isinstance(unavoidable_raw, bool)
    unavoidable_stockout = bool(unavoidable_raw) if unavoidable_stockout_is_bool else False

    aggressive_stockout_risk = _safe_float(
        layer5_intervention.get("aggressive_stockout_risk_proxy")
    )
    risk_threshold = _safe_float(layer5_intervention.get("risk_threshold"))

    signal_thresholds_raw = layer5_intervention.get("signal_thresholds")
    signal_thresholds = signal_thresholds_raw if isinstance(signal_thresholds_raw, dict) else {}
    accelerate_threshold = _safe_float(signal_thresholds.get("accelerate_production"))
    price_slowdown_threshold = _safe_float(
        signal_thresholds.get("increase_price_to_slow_velocity")
    )
    reduce_order_threshold = _safe_float(signal_thresholds.get("reduce_order_size"))

    signals_raw = layer5_intervention.get("signals")
    signals_list = signals_raw if isinstance(signals_raw, list) else []
    signals = [str(item) for item in signals_list]

    known_signals = {
        "accelerate_production",
        "increase_price_to_slow_velocity",
        "reduce_order_size",
    }
    signals_set = set(signals)

    expected_threshold = round(unavoidable_stockout_risk_threshold, 4)
    expected_accelerate_threshold = round(accelerate_production_risk_threshold, 4)
    expected_reduce_order_threshold = round(float(reduce_order_marginal_profit_rate), 4)
    severity_risk_triggered = aggressive_stockout_risk >= accelerate_threshold

    economic_justification_raw = layer5_intervention.get("economic_justification")
    economic_justification = (
        economic_justification_raw
        if isinstance(economic_justification_raw, dict)
        else {}
    )
    overstock_penalty = _safe_float(economic_justification.get("overstock_penalty"))
    marginal_profit_of_additional_units = _safe_float(
        economic_justification.get("marginal_profit_of_additional_units")
    )

    canonical_order = [
        "accelerate_production",
        "increase_price_to_slow_velocity",
        "reduce_order_size",
    ]
    canonical_signals_filtered = [signal for signal in canonical_order if signal in signals_set]

    checks = {
        "method_matches_expected": method == "deterministic_unavoidable_stockout_flags",
        "signal_policy_matches_expected": signal_policy == "critical_risk_thresholds",
        "economic_policy_present": economic_policy == "cost_aware_thresholds",
        "unavoidable_stockout_is_bool": unavoidable_stockout_is_bool,
        "aggressive_risk_in_unit_interval": 0.0 <= aggressive_stockout_risk <= 1.0,
        "thresholds_in_unit_interval": (
            0.0 <= risk_threshold <= 1.0
            and 0.0 <= accelerate_threshold <= 1.0
            and 0.0 <= price_slowdown_threshold <= 1.0
            and 0.0 <= reduce_order_threshold <= 1.0
        ),
        "threshold_sources_match_effective": (
            risk_threshold == expected_threshold
            and accelerate_threshold == expected_accelerate_threshold
            and price_slowdown_threshold == expected_threshold
            and reduce_order_threshold == expected_reduce_order_threshold
        ),
        "threshold_order_valid": accelerate_threshold >= price_slowdown_threshold,
        "risk_threshold_matches_price_slowdown_threshold": (
            risk_threshold == price_slowdown_threshold
        ),
        "signals_known_only": all(signal in known_signals for signal in signals),
        "signals_unique": len(signals) == len(signals_set),
        "signals_order_is_canonical": signals == canonical_signals_filtered,
        "non_unavoidable_has_no_signals_and_none_reason": (
            unavoidable_stockout
            or (not signals and reason == "none")
            or (
                "reduce_order_size" in signals_set
                and reason in {
                    "overstock_penalty_exceeds_marginal_profit",
                    "mixed_risk_and_cost_signals",
                }
            )
        ),
        "unavoidable_has_signals": (
            not unavoidable_stockout
            or len(signals) > 0
        ),
        "reason_consistent_with_signals": (
            (not signals and reason == "none")
            or (
                signals == ["accelerate_production"]
                and reason == "no_effective_in_flight_and_high_stockout_risk"
            )
            or (
                signals == ["increase_price_to_slow_velocity"]
                and reason in {
                    "no_effective_in_flight_but_stockout_risk_persists",
                    "in_flight_present_but_stockout_risk_persists",
                }
            )
            or (
                signals == ["accelerate_production", "increase_price_to_slow_velocity"]
                and reason == "in_flight_present_but_severe_stockout_risk"
            )
            or (
                signals == ["reduce_order_size"]
                and reason == "overstock_penalty_exceeds_marginal_profit"
            )
            or (
                bool(signals)
                and reason == "mixed_risk_and_cost_signals"
            )
        ),
        "accelerate_signal_requires_severe_risk": (
            "accelerate_production" not in signals_set
            or severity_risk_triggered
        ),
        "price_slowdown_signal_requires_unavoidable_threshold": (
            "increase_price_to_slow_velocity" not in signals_set
            or aggressive_stockout_risk >= price_slowdown_threshold
        ),
        "reduce_order_signal_requires_overstock_penalty_gate": (
            "reduce_order_size" not in signals_set
            or overstock_penalty > marginal_profit_of_additional_units
        ),
    }
    return {
        "version": LAYER5_CONTRACT_VERSION,
        "status": "ok" if all(checks.values()) else "violated",
        "signal_count": len(signals),
        "checks": checks,
    }


def _resolve_elastic_binding_scope(
    bindings: list[ProductionOrderElasticBinding],
    line_qty: dict[tuple[int, int], int],
    sku_by_color_size: dict[tuple[int, int], SkuUnit],
) -> tuple[set[int], set[tuple[int, int]]]:
    active_line_keys = {
        key
        for key, qty in line_qty.items()
        if qty > 0
    }
    if not active_line_keys:
        return set(), set()

    active_color_ids = {color_id for color_id, _size_id in active_line_keys}
    active_line_keys_by_sku_id = {
        sku.id: key
        for key, sku in sku_by_color_size.items()
        if key in active_line_keys
    }

    applicable: set[int] = set()
    scoped_line_keys: set[tuple[int, int]] = set()
    for binding in bindings:
        if not binding.is_active:
            continue

        if binding.sku_unit_id is not None:
            line_key = active_line_keys_by_sku_id.get(binding.sku_unit_id)
            if line_key is not None:
                applicable.add(binding.elastic_type_id)
                scoped_line_keys.add(line_key)
                continue

        if binding.color_id is not None and binding.color_id in active_color_ids:
            applicable.add(binding.elastic_type_id)
            for line_key in active_line_keys:
                if line_key[0] == binding.color_id:
                    scoped_line_keys.add(line_key)

    return applicable, scoped_line_keys


def _load_admin_size_weights(
    db: Session,
    article_id: int,
    size_ids: list[int],
) -> dict[int, float]:
    if not size_ids:
        return {}

    rows = (
        db.query(ProductionOrderSizeWeightSetting)
        .filter(
            ProductionOrderSizeWeightSetting.article_id == article_id,
            ProductionOrderSizeWeightSetting.size_id.in_(size_ids),
        )
        .all()
    )

    result: dict[int, float] = {}
    for row in rows:
        if row.weight > 0:
            result[row.size_id] = float(row.weight)

    return result


def _load_wb_bundle_stock(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
) -> dict[int, int]:
    if not bundle_type_ids:
        return {}

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )
    if not mappings:
        return {}

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    if not wb_skus:
        return {}

    stock_rows = (
        db.query(
            WbStock.wb_sku,
            func.sum(WbStock.stock_qty).label("total_qty"),
        )
        .filter(WbStock.wb_sku.in_(wb_skus))
        .group_by(WbStock.wb_sku)
        .all()
    )
    qty_by_wb_sku = {
        str(row.wb_sku): max(int(row.total_qty or 0), 0)
        for row in stock_rows
    }

    stock_by_bundle_type: dict[int, int] = defaultdict(int)
    for mapping in mappings:
        if mapping.bundle_type_id is None:
            continue
        stock_by_bundle_type[mapping.bundle_type_id] += qty_by_wb_sku.get(mapping.wb_sku, 0)

    return dict(stock_by_bundle_type)


def _load_wb_bundle_stock_updated_at_by_bundle(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
) -> dict[int, str | None]:
    if not bundle_type_ids:
        return {}

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )
    if not mappings:
        return {}

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    if not wb_skus:
        return {bundle_type_id: None for bundle_type_id in bundle_type_ids}

    updated_rows = (
        db.query(
            WbStock.wb_sku,
            func.max(WbStock.updated_at).label("last_updated_at"),
        )
        .filter(WbStock.wb_sku.in_(wb_skus))
        .group_by(WbStock.wb_sku)
        .all()
    )
    updated_at_by_wb_sku = {
        str(row.wb_sku): row.last_updated_at
        for row in updated_rows
    }

    latest_updated_at_by_bundle: dict[int, datetime | None] = {
        bundle_type_id: None for bundle_type_id in bundle_type_ids
    }
    for mapping in mappings:
        if mapping.bundle_type_id is None:
            continue

        bundle_type_id = int(mapping.bundle_type_id)
        updated_at = updated_at_by_wb_sku.get(mapping.wb_sku)
        if updated_at is None:
            continue

        current_updated_at = latest_updated_at_by_bundle.get(bundle_type_id)
        if current_updated_at is None or updated_at > current_updated_at:
            latest_updated_at_by_bundle[bundle_type_id] = updated_at

    return {
        bundle_type_id: (updated_at.isoformat() if updated_at is not None else None)
        for bundle_type_id, updated_at in latest_updated_at_by_bundle.items()
    }


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _build_from_wb_freshness_snapshot(
    *,
    effective_as_of_date: date | None,
    wb_stock_updated_at_by_bundle: dict[int, str | None],
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    now: datetime,
) -> tuple[str, int | None, int | None, dict[int, int | None]]:
    anchor_date = now.date()

    sales_age_days_value: int | None = None
    if effective_as_of_date is not None:
        sales_age_days_value = max((anchor_date - effective_as_of_date).days, 0)

    stock_age_days_by_bundle: dict[int, int | None] = {}
    for bundle_type_id, updated_at_text in wb_stock_updated_at_by_bundle.items():
        updated_at = _parse_iso_datetime(updated_at_text)
        if updated_at is None:
            stock_age_days_by_bundle[bundle_type_id] = None
            continue

        stock_age_days_by_bundle[bundle_type_id] = max((anchor_date - updated_at.date()).days, 0)

    stock_known_ages = [age for age in stock_age_days_by_bundle.values() if age is not None]
    stock_oldest_age_days_value = max(stock_known_ages) if stock_known_ages else None

    stale_sales = (
        sales_age_days_value is not None
        and sales_age_days_value > sales_stale_after_days
    )
    stale_stock = (
        stock_oldest_age_days_value is not None
        and stock_oldest_age_days_value > stock_stale_after_days
    )

    if sales_age_days_value is None and stock_oldest_age_days_value is None:
        freshness_status = "no_data"
    elif stale_sales or stale_stock:
        freshness_status = "stale"
    else:
        freshness_status = "fresh"

    return (
        freshness_status,
        sales_age_days_value,
        stock_oldest_age_days_value,
        stock_age_days_by_bundle,
    )


def _resolve_from_wb_freshness_thresholds(
    db: Session,
    article_id: int,
    request_sales_stale_after_days: int | None,
    request_stock_stale_after_days: int | None,
) -> tuple[int, int, dict[str, str]]:
    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )

    admin_sales_stale_after_days = (
        int(article_settings.production_order_freshness_sales_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_sales_stale_after_days is not None
        else None
    )
    admin_stock_stale_after_days = (
        int(article_settings.production_order_freshness_stock_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_stock_stale_after_days is not None
        else None
    )

    if request_sales_stale_after_days is not None:
        sales_stale_after_days = int(request_sales_stale_after_days)
        sales_source = "request"
    elif admin_sales_stale_after_days is not None:
        sales_stale_after_days = admin_sales_stale_after_days
        sales_source = "admin_defaults"
    else:
        sales_stale_after_days = FROM_WB_SALES_STALE_AFTER_DAYS
        sales_source = "global_default"

    if request_stock_stale_after_days is not None:
        stock_stale_after_days = int(request_stock_stale_after_days)
        stock_source = "request"
    elif admin_stock_stale_after_days is not None:
        stock_stale_after_days = admin_stock_stale_after_days
        stock_source = "admin_defaults"
    else:
        stock_stale_after_days = FROM_WB_STOCK_STALE_AFTER_DAYS
        stock_source = "global_default"

    return (
        sales_stale_after_days,
        stock_stale_after_days,
        {
            "sales": sales_source,
            "stock": stock_source,
        },
    )


def _get_wb_mapped_bundle_type_ids(
    db: Session,
    article_id: int,
    bundle_type_ids_filter: list[int] | None = None,
) -> set[int]:
    query = (
        db.query(ArticleWbMapping.bundle_type_id)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.is_not(None),
        )
    )

    if bundle_type_ids_filter:
        query = query.filter(ArticleWbMapping.bundle_type_id.in_(bundle_type_ids_filter))

    rows = query.distinct().all()
    return {int(row.bundle_type_id) for row in rows}


def _resolve_bundle_type_ids_for_from_wb(
    db: Session,
    article_id: int,
    requested_bundle_type_ids: list[int],
) -> list[int]:
    if requested_bundle_type_ids:
        requested = sorted(set(requested_bundle_type_ids))
        mapped = _get_wb_mapped_bundle_type_ids(
            db=db,
            article_id=article_id,
            bundle_type_ids_filter=requested,
        )
        missing = [bundle_type_id for bundle_type_id in requested if bundle_type_id not in mapped]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing WB mapping for bundle_type_id(s): {missing}",
            )
        return requested

    mapped_all = _get_wb_mapped_bundle_type_ids(db=db, article_id=article_id)
    return sorted(mapped_all)


def _load_wb_bundle_daily_sales(
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
    observation_window_days: int,
    as_of_date: date | None,
) -> tuple[dict[int, float], date | None]:
    if not bundle_type_ids:
        return {}, as_of_date

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )

    wb_skus = {mapping.wb_sku for mapping in mappings if mapping.wb_sku}
    effective_as_of_date = as_of_date
    max_sales_date = None

    if wb_skus:
        max_sales_date = (
            db.query(func.max(WbSalesDaily.date))
            .filter(WbSalesDaily.wb_sku.in_(wb_skus))
            .scalar()
        )

    if effective_as_of_date is None and max_sales_date is not None:
        effective_as_of_date = max_sales_date

    if (
        effective_as_of_date is not None
        and max_sales_date is not None
        and effective_as_of_date > max_sales_date
    ):
        effective_as_of_date = max_sales_date

    if effective_as_of_date is None:
        return {bundle_type_id: 0.0 for bundle_type_id in bundle_type_ids}, None

    start_cutoff = effective_as_of_date - timedelta(days=observation_window_days - 1)

    sales_rows = (
        db.query(
            ArticleWbMapping.bundle_type_id,
            func.coalesce(func.sum(WbSalesDaily.sales_qty), 0).label("total_sales_qty"),
        )
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
            WbSalesDaily.date >= start_cutoff,
            WbSalesDaily.date <= effective_as_of_date,
        )
        .group_by(ArticleWbMapping.bundle_type_id)
        .all()
    )

    daily_sales_by_bundle: dict[int, float] = {
        bundle_type_id: 0.0 for bundle_type_id in bundle_type_ids
    }
    for row in sales_rows:
        bundle_type_id = int(row.bundle_type_id)
        total_sales_qty = int(row.total_sales_qty or 0)
        daily_sales_by_bundle[bundle_type_id] = (
            float(total_sales_qty) / float(observation_window_days)
            if observation_window_days > 0
            else 0.0
        )

    return daily_sales_by_bundle, effective_as_of_date


def _summarize_from_wb_price_samples(
    *,
    samples: list[dict[str, float | int]],
    anomaly_max_deviation: float,
) -> dict[str, int | float | bool | None]:
    raw_samples = len(samples)
    if raw_samples <= 0:
        return {
            "price": None,
            "raw_samples": 0,
            "accepted_samples": 0,
            "anomaly_filtered": 0,
            "raw_units": 0,
            "accepted_units": 0,
            "fallback_used": False,
        }

    raw_units = 0
    raw_revenue = 0.0
    accepted_units = 0
    accepted_revenue = 0.0
    accepted_samples = 0
    anomaly_filtered = 0

    for sample in samples:
        qty = max(int(sample.get("qty", 0)), 0)
        revenue = max(float(sample.get("revenue", 0.0)), 0.0)
        if qty <= 0 or revenue <= 0:
            continue

        raw_units += qty
        raw_revenue += revenue
        unit_price = revenue / float(qty)

        if accepted_units > 0:
            baseline_price = accepted_revenue / float(max(accepted_units, 1))
            if baseline_price > 0:
                deviation = abs(unit_price - baseline_price) / baseline_price
                if deviation > anomaly_max_deviation:
                    anomaly_filtered += 1
                    continue

        accepted_units += qty
        accepted_revenue += revenue
        accepted_samples += 1

    fallback_used = False
    observed_price: float | None = None
    if accepted_units > 0:
        observed_price = round(accepted_revenue / float(accepted_units), 4)
    elif raw_units > 0:
        observed_price = round(raw_revenue / float(raw_units), 4)
        fallback_used = True

    return {
        "price": observed_price,
        "raw_samples": raw_samples,
        "accepted_samples": accepted_samples,
        "anomaly_filtered": anomaly_filtered,
        "raw_units": raw_units,
        "accepted_units": accepted_units,
        "fallback_used": fallback_used,
    }


def _load_from_wb_observed_price_calibration(
    *,
    db: Session,
    article_id: int,
    bundle_type_ids: list[int],
    observation_window_days: int,
    effective_as_of_date: date | None,
) -> dict[str, object]:
    empty_summary = _summarize_from_wb_price_samples(
        samples=[],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )
    if effective_as_of_date is None or not bundle_type_ids:
        return {
            "source": FROM_WB_OBSERVED_ECONOMIC_SOURCE,
            "window": {
                "start_date": None,
                "end_date": None,
            },
            "anomaly_max_deviation": FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
            "prices": {
                "main": None,
                "assorti": None,
            },
            "sample_counts": {
                "main": {k: v for k, v in empty_summary.items() if k != "price"},
                "assorti": {k: v for k, v in empty_summary.items() if k != "price"},
            },
        }

    start_cutoff = effective_as_of_date - timedelta(days=observation_window_days - 1)

    bundle_type_rows = (
        db.query(BundleType.id, BundleType.is_assorti)
        .filter(BundleType.id.in_(bundle_type_ids))
        .all()
    )
    assorti_by_bundle_type = {
        int(row.id): bool(row.is_assorti)
        for row in bundle_type_rows
    }

    price_rows = (
        db.query(
            ArticleWbMapping.bundle_type_id,
            WbSalesDaily.date.label("sales_date"),
            func.coalesce(func.sum(WbSalesDaily.sales_qty), 0).label("total_sales_qty"),
            func.coalesce(func.sum(WbSalesDaily.revenue), 0.0).label("total_revenue"),
        )
        .join(WbSalesDaily, WbSalesDaily.wb_sku == ArticleWbMapping.wb_sku)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id.in_(bundle_type_ids),
            WbSalesDaily.date >= start_cutoff,
            WbSalesDaily.date <= effective_as_of_date,
        )
        .group_by(ArticleWbMapping.bundle_type_id, WbSalesDaily.date)
        .order_by(WbSalesDaily.date.asc(), ArticleWbMapping.bundle_type_id.asc())
        .all()
    )

    samples_by_segment: dict[str, list[dict[str, float | int]]] = {
        "main": [],
        "assorti": [],
    }
    for row in price_rows:
        bundle_type_id = int(row.bundle_type_id)
        segment = "assorti" if assorti_by_bundle_type.get(bundle_type_id, False) else "main"
        qty = max(int(row.total_sales_qty or 0), 0)
        revenue = max(float(row.total_revenue or 0.0), 0.0)
        if qty <= 0 or revenue <= 0:
            continue

        samples_by_segment[segment].append(
            {
                "qty": qty,
                "revenue": revenue,
            }
        )

    main_summary = _summarize_from_wb_price_samples(
        samples=samples_by_segment["main"],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )
    assorti_summary = _summarize_from_wb_price_samples(
        samples=samples_by_segment["assorti"],
        anomaly_max_deviation=FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
    )

    return {
        "source": FROM_WB_OBSERVED_ECONOMIC_SOURCE,
        "window": {
            "start_date": start_cutoff.isoformat(),
            "end_date": effective_as_of_date.isoformat(),
        },
        "anomaly_max_deviation": FROM_WB_PRICE_ANOMALY_MAX_DEVIATION,
        "prices": {
            "main": main_summary["price"],
            "assorti": assorti_summary["price"],
        },
        "sample_counts": {
            "main": {k: v for k, v in main_summary.items() if k != "price"},
            "assorti": {k: v for k, v in assorti_summary.items() if k != "price"},
        },
    }


def _normalize_from_wb_commission_ratio(value: object) -> float | None:
    normalized = _normalize_non_negative_float(value)
    if normalized is None:
        return None
    if normalized > 1.0:
        normalized = normalized / 100.0
    return max(min(normalized, 1.0), 0.0)


def _load_from_wb_observed_commission_calibration(
    *,
    db: Session,
) -> dict[str, object]:
    calibration = {
        "source": FROM_WB_TARIFFS_COMMISSION_SOURCE,
        "status": "unavailable",
        "reason": "no_active_account",
        "account_id": None,
        "fetched_rows": 0,
        "subjects_with_commission": 0,
        "commission_percent": {
            "main": None,
            "assorti": None,
        },
        "commission_percent_stats": {
            "avg": None,
            "min": None,
            "max": None,
        },
        "kgvp_supplier_percent_stats": {
            "avg": None,
            "min": None,
            "max": None,
        },
    }

    account = (
        db.query(WbIntegrationAccount)
        .filter(WbIntegrationAccount.is_active.is_(True))
        .order_by(WbIntegrationAccount.id)
        .first()
    )
    if account is None:
        return calibration

    calibration["account_id"] = int(account.id)
    token = (account.api_token or "").strip()
    if not token:
        calibration["reason"] = "empty_api_token"
        return calibration

    try:
        response = httpx.get(
            f"{FROM_WB_TARIFFS_API_BASE_URL}{FROM_WB_TARIFFS_COMMISSION_PATH}",
            headers={"Authorization": token},
            timeout=FROM_WB_TARIFFS_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.RequestError as exc:
        calibration["reason"] = f"request_error:{exc.__class__.__name__}"
        return calibration

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        calibration["reason"] = "unauthorized"
        return calibration
    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        calibration["reason"] = f"wb_api_http_{response.status_code}"
        return calibration

    try:
        payload = response.json()
    except ValueError:
        calibration["reason"] = "invalid_json"
        return calibration

    if not isinstance(payload, dict):
        calibration["reason"] = "invalid_payload"
        return calibration

    report_payload = payload.get("report")
    if not isinstance(report_payload, list):
        calibration["reason"] = "missing_report"
        return calibration

    report_rows: list[dict[str, object]] = []
    for row in report_payload:
        if isinstance(row, dict):
            report_rows.append(row)
    calibration["fetched_rows"] = len(report_rows)

    commission_values: list[float] = []
    for row in report_rows:
        commission_ratio = _normalize_from_wb_commission_ratio(row.get("kgvpSupplier"))
        if commission_ratio is None:
            continue
        commission_values.append(commission_ratio)

    calibration["subjects_with_commission"] = len(commission_values)
    if not commission_values:
        calibration["status"] = "empty_report"
        calibration["reason"] = "no_numeric_commission_values"
        return calibration

    avg_ratio = round(sum(commission_values) / float(len(commission_values)), 4)
    min_ratio = round(min(commission_values), 4)
    max_ratio = round(max(commission_values), 4)

    calibration["status"] = "ok"
    calibration["reason"] = None
    calibration["commission_percent"] = {
        "main": avg_ratio,
        "assorti": avg_ratio,
    }
    calibration["commission_percent_stats"] = {
        "avg": avg_ratio,
        "min": min_ratio,
        "max": max_ratio,
    }
    calibration["kgvp_supplier_percent_stats"] = {
        "avg": round(avg_ratio * 100.0, 4),
        "min": round(min_ratio * 100.0, 4),
        "max": round(max_ratio * 100.0, 4),
    }
    return calibration


def build_production_order_proposal_from_wb(
    db: Session,
    request: ProductionOrderProposalFromWbRequest,
) -> ProductionOrderProposalResponse:
    article = db.query(Article).filter(Article.id == request.article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    bundle_type_ids = _resolve_bundle_type_ids_for_from_wb(
        db=db,
        article_id=request.article_id,
        requested_bundle_type_ids=request.bundle_type_ids,
    )
    if not bundle_type_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No WB-mapped bundle types found for the article",
        )

    daily_sales_by_bundle, effective_as_of_date = _load_wb_bundle_daily_sales(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
        observation_window_days=request.observation_window_days,
        as_of_date=request.as_of_date,
    )
    observed_price_calibration = _load_from_wb_observed_price_calibration(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
        observation_window_days=request.observation_window_days,
        effective_as_of_date=effective_as_of_date,
    )
    observed_commission_calibration = _load_from_wb_observed_commission_calibration(db=db)
    wb_stock_by_bundle = _load_wb_bundle_stock(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
    )
    wb_stock_updated_at_by_bundle = _load_wb_bundle_stock_updated_at_by_bundle(
        db=db,
        article_id=request.article_id,
        bundle_type_ids=bundle_type_ids,
    )
    (
        sales_stale_after_days,
        stock_stale_after_days,
        freshness_threshold_source,
    ) = _resolve_from_wb_freshness_thresholds(
        db=db,
        article_id=request.article_id,
        request_sales_stale_after_days=request.freshness_sales_stale_after_days,
        request_stock_stale_after_days=request.freshness_stock_stale_after_days,
    )
    (
        freshness_status,
        freshness_sales_age_days,
        freshness_stock_oldest_age_days,
        freshness_stock_age_days_by_bundle,
    ) = _build_from_wb_freshness_snapshot(
        effective_as_of_date=effective_as_of_date,
        wb_stock_updated_at_by_bundle=wb_stock_updated_at_by_bundle,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        now=datetime.now(timezone.utc),
    )

    if request.freshness_mode == "strict" and freshness_status != "fresh":
        sales_age_text = "none" if freshness_sales_age_days is None else str(freshness_sales_age_days)
        stock_age_text = (
            "none"
            if freshness_stock_oldest_age_days is None
            else str(freshness_stock_oldest_age_days)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "WB data freshness check failed: "
                f"status={freshness_status}, "
                f"sales_age_days={sales_age_text}, "
                f"stock_oldest_age_days={stock_age_text}, "
                f"thresholds=sales:{sales_stale_after_days}|stock:{stock_stale_after_days}."
            ),
        )

    proposal_request = ProductionOrderProposalRequest(
        article_id=request.article_id,
        planning_horizon_days=request.planning_horizon_days,
        explainability_mode=EXPLAINABILITY_MODE_FULL,
        bundle_daily_sales=[
            BundleDemandInput(
                bundle_type_id=bundle_type_id,
                daily_sales=float(daily_sales_by_bundle.get(bundle_type_id, 0.0)),
            )
            for bundle_type_id in bundle_type_ids
        ],
        bundle_stock=[
            BundleStockInput(
                bundle_type_id=bundle_type_id,
                wb_qty=int(wb_stock_by_bundle.get(bundle_type_id, 0)),
                local_qty=0,
            )
            for bundle_type_id in bundle_type_ids
        ],
        in_flight_supply=request.in_flight_supply,
        size_weights=request.size_weights,
        overrides=request.overrides,
    )

    observed_price_values = observed_price_calibration.get("prices")
    observed_price_source_raw = observed_price_calibration.get("source")
    observed_price_source = (
        observed_price_source_raw
        if isinstance(observed_price_source_raw, str) and observed_price_source_raw.strip()
        else FROM_WB_OBSERVED_ECONOMIC_SOURCE
    )

    observed_commission_values = observed_commission_calibration.get("commission_percent")
    observed_commission_source_raw = observed_commission_calibration.get("source")
    observed_commission_source = (
        observed_commission_source_raw
        if isinstance(observed_commission_source_raw, str) and observed_commission_source_raw.strip()
        else FROM_WB_TARIFFS_COMMISSION_SOURCE
    )

    runtime_economic_overrides: dict[str, float | None] = {}
    runtime_economic_source_overrides: dict[str, str] = {}

    if isinstance(observed_price_values, dict):
        price_main = _normalize_non_negative_float(observed_price_values.get("main"))
        if price_main is not None:
            runtime_economic_overrides["average_realized_price_main"] = price_main
            runtime_economic_source_overrides["average_realized_price_main"] = observed_price_source

        price_assorti = _normalize_non_negative_float(observed_price_values.get("assorti"))
        if price_assorti is not None:
            runtime_economic_overrides["average_realized_price_assorti"] = price_assorti
            runtime_economic_source_overrides["average_realized_price_assorti"] = observed_price_source

    if isinstance(observed_commission_values, dict):
        commission_main = _normalize_from_wb_commission_ratio(observed_commission_values.get("main"))
        if commission_main is not None:
            runtime_economic_overrides["wb_commission_percent_main"] = commission_main
            runtime_economic_source_overrides["wb_commission_percent_main"] = observed_commission_source

        commission_assorti = _normalize_from_wb_commission_ratio(
            observed_commission_values.get("assorti")
        )
        if commission_assorti is not None:
            runtime_economic_overrides["wb_commission_percent_assorti"] = commission_assorti
            runtime_economic_source_overrides["wb_commission_percent_assorti"] = observed_commission_source

    runtime_overrides_payload = runtime_economic_overrides or None
    runtime_source_overrides_payload = runtime_economic_source_overrides or None

    response = build_production_order_proposal(
        db=db,
        request=proposal_request,
        runtime_economic_overrides=runtime_overrides_payload,
        runtime_economic_source=FROM_WB_OBSERVED_ECONOMIC_SOURCE,
        runtime_economic_source_overrides=runtime_source_overrides_payload,
    )
    requested_as_of_text = request.as_of_date.isoformat() if request.as_of_date is not None else "none"
    as_of_text = effective_as_of_date.isoformat() if effective_as_of_date is not None else "none"
    if effective_as_of_date is None:
        as_of_source = "none"
    elif request.as_of_date is None:
        as_of_source = "latest_sales"
    elif request.as_of_date != effective_as_of_date:
        as_of_source = "clamped_to_latest_sales"
    else:
        as_of_source = "request"

    if effective_as_of_date is not None:
        window_start_date = (
            effective_as_of_date - timedelta(days=request.observation_window_days - 1)
        ).isoformat()
        window_end_date = effective_as_of_date.isoformat()
        window_text = f"{window_start_date}..{as_of_text}"
    else:
        window_start_date = None
        window_end_date = None
        window_text = "none"
    daily_sales_snapshot = {
        bundle_type_id: round(float(daily_sales_by_bundle.get(bundle_type_id, 0.0)), 4)
        for bundle_type_id in bundle_type_ids
    }
    wb_stock_snapshot = {
        bundle_type_id: int(wb_stock_by_bundle.get(bundle_type_id, 0))
        for bundle_type_id in bundle_type_ids
    }
    freshness_sales_age_days_text = (
        "none" if freshness_sales_age_days is None else str(freshness_sales_age_days)
    )
    freshness_stock_oldest_age_days_text = (
        "none" if freshness_stock_oldest_age_days is None else str(freshness_stock_oldest_age_days)
    )

    response.explanation.meta["from_wb"] = {
        "observation_window_days": request.observation_window_days,
        "freshness_mode": request.freshness_mode,
        "requested_as_of_date": request.as_of_date.isoformat() if request.as_of_date else None,
        "as_of_date": effective_as_of_date.isoformat() if effective_as_of_date else None,
        "as_of_source": as_of_source,
        "bundle_type_ids": bundle_type_ids,
        "sales_window": (
            {
                "start_date": window_start_date,
                "end_date": window_end_date,
            }
            if window_start_date is not None and window_end_date is not None
            else None
        ),
        "daily_sales_by_bundle": daily_sales_snapshot,
        "wb_stock_by_bundle": wb_stock_snapshot,
        "wb_stock_updated_at_by_bundle": wb_stock_updated_at_by_bundle,
        "economic_observed_prices": observed_price_calibration,
        "economic_observed_commission": observed_commission_calibration,
        "freshness": {
            "status": freshness_status,
            "sales_age_days": freshness_sales_age_days,
            "stock_oldest_age_days": freshness_stock_oldest_age_days,
            "stock_age_days_by_bundle": freshness_stock_age_days_by_bundle,
            "threshold_days": {
                "sales": sales_stale_after_days,
                "stock": stock_stale_after_days,
            },
            "threshold_source": freshness_threshold_source,
        },
    }

    response.explanation.steps.insert(
        0,
        (
            "WB ingestion adapter: "
            f"observation_window_days={request.observation_window_days}, "
            f"freshness_mode={request.freshness_mode}, "
            f"requested_as_of_date={requested_as_of_text}, "
            f"as_of_date={as_of_text}, as_of_source={as_of_source}, "
            f"bundle_type_ids={bundle_type_ids}."
            f" sales_window={window_text},"
            f" daily_sales_by_bundle={daily_sales_snapshot}, "
            f"wb_stock_by_bundle={wb_stock_snapshot}, "
            f"wb_stock_updated_at_by_bundle={wb_stock_updated_at_by_bundle}, "
            f"economic_observed_prices={observed_price_calibration.get('prices')}, "
            f"economic_observed_source={observed_price_calibration.get('source')}, "
            f"economic_observed_commission={observed_commission_calibration.get('commission_percent')}, "
            f"economic_observed_commission_status={observed_commission_calibration.get('status')}, "
            f"economic_observed_commission_source={observed_commission_calibration.get('source')}, "
            f"freshness_status={freshness_status}, "
            f"freshness_sales_age_days={freshness_sales_age_days_text}, "
            f"freshness_stock_oldest_age_days={freshness_stock_oldest_age_days_text}, "
            f"freshness_stock_age_days_by_bundle={freshness_stock_age_days_by_bundle}, "
            f"freshness_threshold_days=sales:{sales_stale_after_days}|stock:{stock_stale_after_days}, "
            f"freshness_threshold_source=sales:{freshness_threshold_source['sales']}|stock:{freshness_threshold_source['stock']}."
        ),
    )
    response.explanation = _apply_explainability_mode(
        explanation=response.explanation,
        mode=request.explainability_mode,
    )
    return response


def _in_flight_stage_factor(stage: str | None) -> float:
    stage_key = (stage or "other").strip().lower()
    stage_factors: dict[str, float] = {
        "production": 0.85,
        "china_to_nsk": 0.90,
        "packaging": 0.97,
        "nsk_to_wb": 1.00,
        "other": 0.80,
    }
    return stage_factors.get(stage_key, stage_factors["other"])


def _estimate_effective_in_flight_qty(
    qty: int,
    eta_days: int,
    lead_time_days_total: int,
    stage: str | None,
) -> int:
    if qty <= 0:
        return 0

    eta = max(int(eta_days), 0)
    lead_time = max(int(lead_time_days_total), 0)

    if lead_time > 0 and eta > lead_time:
        return 0

    if lead_time <= 0:
        eta_factor = 1.0
    else:
        eta_factor = (lead_time - eta + 1) / (lead_time + 1)
        eta_factor = max(min(eta_factor, 1.0), 0.0)

    stage_factor = _in_flight_stage_factor(stage)
    effective = floor(qty * eta_factor * stage_factor)
    return max(int(effective), 0)


def _compute_economic_buffer_days(
    *,
    risk_level: str,
    allow_order_with_buffer: bool,
    total_daily_sales: float,
    lead_time_days_total: int,
    days_of_cover_estimate: float,
) -> int:
    if not allow_order_with_buffer or total_daily_sales <= 0:
        return 0

    if risk_level not in {"critical", "warning"}:
        return 0

    cover_gap_days = max(float(lead_time_days_total) - max(days_of_cover_estimate, 0.0), 0.0)
    if cover_gap_days <= 0:
        return 0

    buffer_days = _ceil_to_int(cover_gap_days * 0.35)
    if risk_level == "critical":
        buffer_days += 2
    else:
        buffer_days += 1

    return max(min(buffer_days, 14), 0)


def _estimate_competition_aware_raw_bundle_stock(
    *,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    stock_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
) -> dict[int, int]:
    raw_by_bundle: dict[int, int] = {bundle_type_id: 0 for bundle_type_id in bundle_type_ids}

    color_consumers: dict[int, list[int]] = {}
    for color_id in all_recipe_color_ids:
        color_consumers[color_id] = [
            bundle_type_id
            for bundle_type_id in bundle_type_ids
            if color_id in recipe_colors_by_bundle.get(bundle_type_id, set())
        ]

    for size_id in size_ids:
        color_bundle_alloc: dict[tuple[int, int], int] = {}

        for color_id in all_recipe_color_ids:
            color_qty = max(stock_by_color_size.get((color_id, size_id), 0), 0)
            if color_qty <= 0:
                continue

            consumers = color_consumers.get(color_id, [])
            if not consumers:
                continue

            if len(consumers) == 1:
                color_bundle_alloc[(color_id, consumers[0])] = color_qty
                continue

            consumer_weights = _normalize_weights(
                consumers,
                {bundle_type_id: shares_by_bundle.get(bundle_type_id, 0.0) for bundle_type_id in consumers},
            )
            allocated = _allocate_units(color_qty, consumer_weights)
            for bundle_type_id, allocated_qty in allocated.items():
                if allocated_qty <= 0:
                    continue
                color_bundle_alloc[(color_id, bundle_type_id)] = allocated_qty

        for bundle_type_id in bundle_type_ids:
            recipe_colors = recipe_colors_by_bundle.get(bundle_type_id, set())
            if not recipe_colors:
                continue

            color_quantities = [
                color_bundle_alloc.get((color_id, bundle_type_id), 0) for color_id in recipe_colors
            ]
            if not color_quantities or any(quantity <= 0 for quantity in color_quantities):
                continue

            raw_by_bundle[bundle_type_id] += min(color_quantities)

    return raw_by_bundle


def _load_admin_in_flight_defaults(
    db: Session,
    article_id: int,
) -> list[ProductionOrderInFlightDefault]:
    return (
        db.query(ProductionOrderInFlightDefault)
        .filter(
            ProductionOrderInFlightDefault.article_id == article_id,
            ProductionOrderInFlightDefault.is_active.is_(True),
            ProductionOrderInFlightDefault.qty > 0,
        )
        .all()
    )


def build_production_order_proposal(
    db: Session,
    request: ProductionOrderProposalRequest,
    *,
    runtime_economic_overrides: dict[str, float | None] | None = None,
    runtime_economic_source: str | None = None,
    runtime_economic_source_overrides: dict[str, str] | None = None,
) -> ProductionOrderProposalResponse:
    now = datetime.now(timezone.utc)

    article = db.query(Article).filter(Article.id == request.article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == request.article_id)
        .first()
    )
    planning_settings = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == request.article_id)
        .first()
    )
    global_settings = (
        db.query(GlobalPlanningSettings).order_by(GlobalPlanningSettings.id).first()
    )

    settings = _build_effective_settings(
        article_settings=article_settings,
        planning_settings=planning_settings,
        global_settings=global_settings,
        overrides=request.overrides,
    )
    layer_proxy_settings = _resolve_layer_proxy_settings(
        article_settings=article_settings,
        global_settings=global_settings,
        overrides=request.overrides,
    )
    economic_settings = _resolve_economic_settings(
        article_settings=article_settings,
        global_settings=global_settings,
        overrides=request.overrides,
        runtime_overrides=runtime_economic_overrides,
        runtime_source=runtime_economic_source,
        runtime_source_overrides=runtime_economic_source_overrides,
    )

    if not settings.include_in_planning:
        explanation = _apply_explainability_mode(
            explanation=ProductionOrderExplanationBlock(
                summary="Артикул исключен из планирования настройкой include_in_planning=false.",
                steps=[
                    "Получены настройки статьи и проверен флаг include_in_planning.",
                    "Расчет пропущен по явному правилу исключения.",
                ],
            ),
            mode=request.explainability_mode,
        )

        return ProductionOrderProposalResponse(
            status="skipped",
            article_id=request.article_id,
            generated_at=now,
            risk_level="no_data",
            days_of_cover_estimate=0.0,
            lead_time_days_total=settings.lead_time_days_total,
            recommendation=None,
            constraints_applied=ProductionOrderConstraintsApplied(),
            alternatives=[],
            explanation=explanation,
        )

    economics_trust = _build_economics_trust_diagnostics(economic_settings.source)
    economics_warnings = list(economics_trust.get("warnings", []))
    if economic_settings.available_capital is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": (
                    "available_capital is required for production-order proposal in strict capital "
                    "governance mode"
                ),
                "capital_constraint_status": CAPITAL_CONSTRAINT_STATUS_MISSING_STRICT,
                "severity": "HIGH",
                "action": (
                    "Provide overrides.available_capital or configure article/global available_capital "
                    "defaults."
                ),
                "economics_trust_level": economics_trust.get("economics_trust_level"),
            },
        )

    bundle_type_ids = sorted({item.bundle_type_id for item in request.bundle_daily_sales})

    recipes = (
        db.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == request.article_id,
            BundleRecipe.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )

    if not recipes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No bundle recipe defined for the provided article and bundle types",
        )

    recipe_colors_by_bundle: dict[int, set[int]] = defaultdict(set)
    for recipe in recipes:
        recipe_colors_by_bundle[recipe.bundle_type_id].add(recipe.color_id)

    missing_bundle_types = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if not recipe_colors_by_bundle.get(bundle_type_id)
    ]
    if missing_bundle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No bundle recipe defined for bundle_type_id(s): {missing_bundle_types}",
        )

    all_recipe_color_ids = sorted({color_id for colors in recipe_colors_by_bundle.values() for color_id in colors})

    sku_units = (
        db.query(SkuUnit)
        .filter(
            SkuUnit.article_id == request.article_id,
            SkuUnit.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )

    if not sku_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No SKU units found for article and recipe colors",
        )

    sku_by_color_size: dict[tuple[int, int], SkuUnit] = {}
    color_to_sizes: dict[int, list[int]] = defaultdict(list)
    size_ids_set: set[int] = set()
    for sku in sku_units:
        sku_by_color_size[(sku.color_id, sku.size_id)] = sku
        color_to_sizes[sku.color_id].append(sku.size_id)
        size_ids_set.add(sku.size_id)

    size_ids = sorted(size_ids_set)
    for color_id in color_to_sizes:
        color_to_sizes[color_id] = sorted(set(color_to_sizes[color_id]))

    requested_size_weights = {
        int(size_id): float(weight) for size_id, weight in request.size_weights.items() if weight > 0
    }
    size_weights_source = "request"
    if not requested_size_weights:
        requested_size_weights = _load_admin_size_weights(
            db=db,
            article_id=request.article_id,
            size_ids=size_ids,
        )
        if requested_size_weights:
            size_weights_source = "admin_defaults"
        else:
            size_weights_source = "uniform_fallback"

    size_weights = _normalize_weights(size_ids, requested_size_weights)

    stock_agg_rows = (
        db.query(
            StockBalance.sku_unit_id,
            func.sum(StockBalance.quantity).label("total_qty"),
        )
        .filter(StockBalance.sku_unit_id.in_([sku.id for sku in sku_units]))
        .group_by(StockBalance.sku_unit_id)
        .all()
    )
    stock_by_sku_id = {
        int(row.sku_unit_id): max(int(row.total_qty or 0), 0) for row in stock_agg_rows
    }

    stock_by_color_size: dict[tuple[int, int], int] = {}
    for sku in sku_units:
        stock_by_color_size[(sku.color_id, sku.size_id)] = stock_by_sku_id.get(sku.id, 0)
    current_stock_by_color_size = dict(stock_by_color_size)

    effective_in_flight_supply = list(request.in_flight_supply)
    in_flight_source = "request"

    if not effective_in_flight_supply:
        admin_defaults = _load_admin_in_flight_defaults(
            db=db,
            article_id=request.article_id,
        )
        if admin_defaults:
            in_flight_source = "admin_defaults"
            for row in admin_defaults:
                effective_in_flight_supply.append(row)
        else:
            in_flight_source = "none"

    in_flight_raw_qty_total = 0
    in_flight_effective_qty_total = 0
    in_flight_effective_lines = 0
    in_flight_effective_by_color_size: dict[tuple[int, int], int] = defaultdict(int)
    in_flight_eta_days_by_color_size: dict[tuple[int, int], int] = {}

    # Add in-flight supply with ETA/stage sensitivity.
    for in_flight in effective_in_flight_supply:
        if in_flight.article_id != request.article_id:
            continue

        key = (in_flight.color_id, in_flight.size_id)
        if key not in sku_by_color_size:
            continue

        raw_qty = max(int(in_flight.qty), 0)
        if raw_qty <= 0:
            continue

        in_flight_raw_qty_total += raw_qty
        eta_days = int(in_flight.eta_days)
        existing_eta = in_flight_eta_days_by_color_size.get(key)
        if existing_eta is None or eta_days < existing_eta:
            in_flight_eta_days_by_color_size[key] = eta_days

        effective_qty = _estimate_effective_in_flight_qty(
            qty=raw_qty,
            eta_days=eta_days,
            lead_time_days_total=settings.lead_time_days_total,
            stage=getattr(in_flight, "stage", "other"),
        )
        if effective_qty <= 0:
            continue

        in_flight_effective_qty_total += effective_qty
        in_flight_effective_lines += 1
        in_flight_effective_by_color_size[key] += effective_qty

        stock_by_color_size[key] = stock_by_color_size.get(key, 0) + effective_qty

    demand_by_bundle = {item.bundle_type_id: item.daily_sales for item in request.bundle_daily_sales}
    total_daily_sales = float(sum(demand_by_bundle.values()))

    stock_by_bundle = {
        item.bundle_type_id: item.wb_qty + item.local_qty for item in request.bundle_stock
    }
    bundle_stock_source = "request"

    missing_bundle_type_ids = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if bundle_type_id not in stock_by_bundle
    ]
    if missing_bundle_type_ids:
        wb_bundle_stock = _load_wb_bundle_stock(
            db=db,
            article_id=request.article_id,
            bundle_type_ids=missing_bundle_type_ids,
        )
        for bundle_type_id in missing_bundle_type_ids:
            if bundle_type_id in wb_bundle_stock:
                stock_by_bundle[bundle_type_id] = wb_bundle_stock[bundle_type_id]

        if wb_bundle_stock:
            if request.bundle_stock:
                bundle_stock_source = "mixed_request_plus_wb"
            else:
                bundle_stock_source = "wb_defaults"
        elif not request.bundle_stock:
            bundle_stock_source = "none"

    ready_bundle_stock_total = sum(stock_by_bundle.get(bundle_type_id, 0) for bundle_type_id in bundle_type_ids)

    shares_by_bundle: dict[int, float] = {}
    if total_daily_sales > 0:
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = demand_by_bundle.get(bundle_type_id, 0.0) / total_daily_sales
    else:
        equal_share = 1.0 / len(bundle_type_ids)
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = equal_share

    competition_raw_by_bundle = _estimate_competition_aware_raw_bundle_stock(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        all_recipe_color_ids=all_recipe_color_ids,
        size_ids=size_ids,
        stock_by_color_size=stock_by_color_size,
        shares_by_bundle=shares_by_bundle,
    )
    competition_raw_bundle_stock = sum(competition_raw_by_bundle.values())
    competition_raw_breakdown = ", ".join(
        f"{bundle_type_id}:{competition_raw_by_bundle.get(bundle_type_id, 0)}"
        for bundle_type_id in bundle_type_ids
    )

    available_bundles_for_cover = ready_bundle_stock_total + competition_raw_bundle_stock
    reorder_point_days = settings.lead_time_days_total + settings.safety_stock_days

    admin_assorti_bundle_type_ids = _parse_assorti_bundle_type_ids(
        article_settings.production_order_assorti_bundle_type_ids
        if article_settings is not None
        else None
    )
    global_assorti_bundle_type_ids = _parse_assorti_bundle_type_ids(
        global_settings.default_production_order_assorti_bundle_type_ids
        if global_settings is not None
        else None
    )

    assorti_by_bundle_type, assorti_classification_by_bundle_type = _load_assorti_bundle_type_flags(
        db=db,
        bundle_type_ids=bundle_type_ids,
        admin_assorti_bundle_type_ids=admin_assorti_bundle_type_ids,
        global_assorti_bundle_type_ids=global_assorti_bundle_type_ids,
    )
    assorti_bundle_type_count = sum(
        1
        for item in assorti_classification_by_bundle_type
        if bool(item.get("is_assorti"))
    )
    main_bundle_type_count = max(
        len(assorti_classification_by_bundle_type) - assorti_bundle_type_count,
        0,
    )
    assorti_classification_source_counts: dict[str, int] = defaultdict(int)
    for item in assorti_classification_by_bundle_type:
        source = str(item.get("source", "unknown"))
        assorti_classification_source_counts[source] += 1
    assorti_classification_source_breakdown = {
        source: assorti_classification_source_counts[source]
        for source in sorted(assorti_classification_source_counts)
    }

    layer1_stock_health_metrics = _build_layer1_stock_health_metrics(
        bundle_type_ids=bundle_type_ids,
        demand_by_bundle=demand_by_bundle,
        recipe_colors_by_bundle=recipe_colors_by_bundle,
        color_to_sizes=color_to_sizes,
        size_weights=size_weights,
        current_stock_by_color_size=stock_by_color_size,
        in_flight_effective_by_color_size=in_flight_effective_by_color_size,
        in_flight_eta_days_by_color_size=in_flight_eta_days_by_color_size,
        assorti_by_bundle_type=assorti_by_bundle_type,
        reorder_point_days=reorder_point_days,
        target_coverage_days=settings.target_coverage_days,
        margin_main_per_unit=economic_settings.margin_main_per_unit,
        margin_assorti_per_unit=economic_settings.margin_assorti_per_unit,
        unit_capital_per_unit=economic_settings.unit_capital_per_unit,
    )
    layer2_allocation_decisions, layer2_allocation_summary = _build_layer2_allocation_decisions(
        stock_health_metrics=layer1_stock_health_metrics,
        lead_time_days_total=settings.lead_time_days_total,
        margin_main_per_unit=economic_settings.margin_main_per_unit,
        margin_assorti_per_unit=economic_settings.margin_assorti_per_unit,
        unit_capital_per_unit=economic_settings.unit_capital_per_unit,
        capital_cost_rate=layer_proxy_settings.layer2_capital_cost_rate,
        stockout_penalty_weight=layer_proxy_settings.layer2_stockout_penalty_weight,
        overstock_penalty_weight=layer_proxy_settings.layer2_overstock_penalty_weight,
    )
    layer2_contract = _build_layer2_contract_summary(
        layer2_allocation_decisions=layer2_allocation_decisions,
        layer2_allocation_summary=layer2_allocation_summary,
    )
    layer2_decision_quality = _build_layer2_decision_quality_summary(
        layer2_allocation_decisions=layer2_allocation_decisions,
    )
    layer1_avg_coverage_days = (
        round(
            sum(float(item["coverage_days"]) for item in layer1_stock_health_metrics)
            / len(layer1_stock_health_metrics),
            2,
        )
        if layer1_stock_health_metrics
        else 0.0
    )
    layer1_high_stockout_risk_count = sum(
        1
        for item in layer1_stock_health_metrics
        if float(item["stockout_risk"]) >= LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD
    )
    layer1_contract = _build_layer1_contract_summary(layer1_stock_health_metrics)

    if total_daily_sales <= 0:
        days_of_cover_estimate = 9999.0
        risk_level = "no_data"
    else:
        days_of_cover_estimate = available_bundles_for_cover / total_daily_sales
        if days_of_cover_estimate < reorder_point_days:
            risk_level = "critical"
        elif days_of_cover_estimate < settings.alert_threshold_days:
            risk_level = "warning"
        elif days_of_cover_estimate > settings.target_coverage_days * 2:
            risk_level = "overstock"
        else:
            risk_level = "ok"

    economic_buffer_days = _compute_economic_buffer_days(
        risk_level=risk_level,
        allow_order_with_buffer=settings.allow_order_with_buffer,
        total_daily_sales=total_daily_sales,
        lead_time_days_total=settings.lead_time_days_total,
        days_of_cover_estimate=days_of_cover_estimate,
    )
    target_bundle_horizon_days = (
        settings.target_coverage_days
        + settings.lead_time_days_total
        + settings.safety_stock_days
        + economic_buffer_days
    )

    required_bundle_units = _ceil_to_int(
        total_daily_sales * target_bundle_horizon_days
    )
    bundle_deficit_total = max(required_bundle_units - available_bundles_for_cover, 0)

    color_probability: dict[int, float] = {color_id: 0.0 for color_id in all_recipe_color_ids}
    for color_id in all_recipe_color_ids:
        for bundle_type_id in bundle_type_ids:
            if color_id in recipe_colors_by_bundle[bundle_type_id]:
                color_probability[color_id] += shares_by_bundle.get(bundle_type_id, 0.0)

    if sum(color_probability.values()) <= 0:
        uniform = 1.0 / len(all_recipe_color_ids)
        color_probability = {color_id: uniform for color_id in all_recipe_color_ids}

    line_required: dict[tuple[int, int], int] = {}
    for color_id in all_recipe_color_ids:
        color_target_units = _ceil_to_int(bundle_deficit_total * color_probability.get(color_id, 0.0))
        sizes_for_color = color_to_sizes.get(color_id, [])
        if not sizes_for_color:
            continue

        local_weights = _normalize_weights(
            sizes_for_color,
            {size_id: size_weights.get(size_id, 0.0) for size_id in sizes_for_color},
        )
        allocated = _allocate_units(color_target_units, local_weights)

        for size_id, qty in allocated.items():
            line_required[(color_id, size_id)] = qty

    line_qty: dict[tuple[int, int], int] = {}
    for key, required_qty in line_required.items():
        current_qty = stock_by_color_size.get(key, 0)
        line_qty[key] = max(required_qty - current_qty, 0)

    layer3_decision_by_line, layer3_purchase_shaping = _apply_layer3_purchase_shaping(
        line_qty=line_qty,
        layer2_allocation_decisions=layer2_allocation_decisions,
        layer1_stock_health_metrics=layer1_stock_health_metrics,
        layer3_stockout_boost_max=layer_proxy_settings.layer3_stockout_boost_max,
        layer3_overstock_dampen_max=layer_proxy_settings.layer3_overstock_dampen_max,
    )
    layer3_contract = _build_layer3_contract_summary(layer3_purchase_shaping)

    color_totals: dict[int, int] = defaultdict(int)
    for (color_id, _size_id), qty in line_qty.items():
        color_totals[color_id] += qty

    colors = db.query(Color).filter(Color.id.in_(all_recipe_color_ids)).all()
    pantone_by_color: dict[int, str] = {}
    for color in colors:
        pantone_by_color[color.id] = color.pantone_code or f"COLOR-{color.id}"

    color_settings_rows = (
        db.query(ColorPlanningSettings)
        .filter(
            ColorPlanningSettings.article_id == request.article_id,
            ColorPlanningSettings.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )
    color_min_override = {
        row.color_id: row.fabric_min_batch_qty
        for row in color_settings_rows
        if row.fabric_min_batch_qty is not None and row.fabric_min_batch_qty > 0
    }

    constraints_applied = ProductionOrderConstraintsApplied()

    colors_by_pantone: dict[str, list[int]] = defaultdict(list)
    for color_id in all_recipe_color_ids:
        colors_by_pantone[pantone_by_color.get(color_id, f"COLOR-{color_id}")].append(color_id)

    for pantone_code, pantone_color_ids in sorted(colors_by_pantone.items(), key=lambda item: item[0]):
        required_qty = sum(color_totals.get(color_id, 0) for color_id in pantone_color_ids)
        if required_qty <= 0:
            continue

        min_candidates = [settings.fabric_min_batch_default]
        for color_id in pantone_color_ids:
            override_value = color_min_override.get(color_id)
            if override_value is not None:
                min_candidates.append(override_value)

        applied_min = max(min_candidates)
        if required_qty >= applied_min:
            continue

        delta = applied_min - required_qty
        constraints_applied.fabric_min_batches.append(
            FabricConstraintApplied(
                pantone_code=pantone_code,
                required=required_qty,
                applied_min=applied_min,
            )
        )

        if len(pantone_color_ids) == 1:
            _add_units_for_color(
                line_qty=line_qty,
                color_id=pantone_color_ids[0],
                additional_qty=delta,
                color_to_sizes=color_to_sizes,
                global_size_weights=size_weights,
            )
        else:
            total_color_weight = sum(max(color_totals.get(color_id, 0), 1) for color_id in pantone_color_ids)
            color_weights = {
                color_id: max(color_totals.get(color_id, 0), 1) / total_color_weight
                for color_id in pantone_color_ids
            }
            color_alloc = _allocate_units(delta, color_weights)
            for color_id, qty in color_alloc.items():
                _add_units_for_color(
                    line_qty=line_qty,
                    color_id=color_id,
                    additional_qty=qty,
                    color_to_sizes=color_to_sizes,
                    global_size_weights=size_weights,
                )

        # Recalculate color totals after updates.
        color_totals = defaultdict(int)
        for (color_id, _size_id), qty in line_qty.items():
            color_totals[color_id] += qty

    elastic_rows = (
        db.query(ElasticPlanningSettings)
        .filter(ElasticPlanningSettings.article_id == request.article_id)
        .all()
    )

    elastic_bindings = (
        db.query(ProductionOrderElasticBinding)
        .filter(
            ProductionOrderElasticBinding.article_id == request.article_id,
            ProductionOrderElasticBinding.is_active.is_(True),
        )
        .all()
    )

    applicable_elastic_type_ids, elastic_scope_line_keys = _resolve_elastic_binding_scope(
        bindings=elastic_bindings,
        line_qty=line_qty,
        sku_by_color_size=sku_by_color_size,
    )

    scoped_elastic_rows = list(elastic_rows)
    elastic_scope_mode = "all_types"
    if elastic_bindings:
        elastic_scope_mode = "binding_scope"
        if applicable_elastic_type_ids:
            scoped_elastic_rows = [
                row for row in elastic_rows if row.elastic_type_id in applicable_elastic_type_ids
            ]
        else:
            scoped_elastic_rows = []

    current_total_units = sum(line_qty.values())

    elastic_target = settings.elastic_min_batch_default
    elastic_type_id: int | None = None

    if elastic_bindings and not applicable_elastic_type_ids:
        elastic_target = 0

    for row in scoped_elastic_rows:
        candidate = row.elastic_min_batch_qty
        if candidate is None or candidate <= 0:
            candidate = settings.elastic_min_batch_default

        if candidate > elastic_target:
            elastic_target = candidate
            elastic_type_id = row.elastic_type_id

    elastic_uplift_delta = 0
    elastic_uplift_scope = "none"
    elastic_uplift_keys: list[tuple[int, int]] = []
    elastic_uplift_line_alloc: dict[tuple[int, int], int] = {}

    if current_total_units > 0 and elastic_target > 0 and current_total_units < elastic_target:
        delta = elastic_target - current_total_units
        elastic_uplift_delta = delta
        constraints_applied.elastic_min_batches.append(
            ElasticConstraintApplied(
                article_id=request.article_id,
                elastic_type_id=elastic_type_id,
                required=current_total_units,
                applied_min=elastic_target,
            )
        )

        if line_qty:
            if elastic_bindings and elastic_scope_line_keys:
                keys = sorted(elastic_scope_line_keys)
                elastic_uplift_scope = "binding_scope"
            else:
                keys = sorted(line_qty.keys())
                elastic_uplift_scope = "all_lines"
            elastic_uplift_keys = list(keys)
            base_add = delta // len(keys)
            rem = delta % len(keys)
            for index, key in enumerate(keys):
                add_qty = base_add + (1 if index < rem else 0)
                line_qty[key] += add_qty
                if add_qty > 0:
                    elastic_uplift_line_alloc[key] = add_qty

    candidate_lines: list[ProductionOrderRecommendationLine] = []
    for (color_id, size_id), qty in sorted(line_qty.items(), key=lambda item: (item[0][0], item[0][1])):
        if qty <= 0:
            continue
        layer2_decision = layer3_decision_by_line.get((color_id, size_id), "main")
        candidate_lines.append(
            ProductionOrderRecommendationLine(
                article_id=request.article_id,
                color_id=color_id,
                size_id=size_id,
                recommended_qty=qty,
                source_reason=(
                    "deficit_plus_min_batch_alignment"
                    f"|layer2:{layer2_decision}"
                ),
            )
        )

    capital_rankings = _build_line_objective_capital_rankings(
        candidate_lines=candidate_lines,
        layer3_decision_by_line=layer3_decision_by_line,
        layer1_stock_health_metrics=layer1_stock_health_metrics,
        margin_main_per_unit=economic_settings.margin_main_per_unit,
        margin_assorti_per_unit=economic_settings.margin_assorti_per_unit,
        unit_capital_per_unit=economic_settings.unit_capital_per_unit,
        capital_cost_rate=layer_proxy_settings.layer2_capital_cost_rate,
        stockout_penalty_weight=layer_proxy_settings.layer2_stockout_penalty_weight,
        overstock_penalty_weight=layer_proxy_settings.layer2_overstock_penalty_weight,
    )
    candidate_lines, capital_constraint_summary = _apply_capital_constraint_to_candidate_lines(
        candidate_lines=candidate_lines,
        ranked_line_objectives=capital_rankings,
        available_capital=economic_settings.available_capital,
        unit_capital_per_unit=economic_settings.unit_capital_per_unit,
    )
    capital_constraint_contract = _build_capital_constraint_contract_summary(
        capital_constraint_summary,
    )
    capital_constraint_summary = {
        **capital_constraint_summary,
        "contract": capital_constraint_contract,
    }

    candidate_total_units = sum(line.recommended_qty for line in candidate_lines)
    expected_horizon_sales = total_daily_sales * request.planning_horizon_days
    layer4_scenarios = _build_layer4_scenarios(
        base_purchase_units=candidate_total_units,
        available_bundles_for_cover=available_bundles_for_cover,
        total_daily_sales=total_daily_sales,
        reorder_point_days=reorder_point_days,
        expected_horizon_sales=expected_horizon_sales,
        layer3_purchase_shaping=layer3_purchase_shaping,
        unit_capital_per_unit=economic_settings.unit_capital_per_unit,
        margin_main_per_unit=economic_settings.margin_main_per_unit,
        margin_assorti_per_unit=economic_settings.margin_assorti_per_unit,
        average_realized_price_main=economic_settings.average_realized_price_main,
        average_realized_price_assorti=economic_settings.average_realized_price_assorti,
        capital_cost_rate=layer_proxy_settings.layer2_capital_cost_rate,
        stockout_penalty_weight=layer_proxy_settings.layer2_stockout_penalty_weight,
        overstock_penalty_weight=layer_proxy_settings.layer2_overstock_penalty_weight,
    )
    capital_gap_summary = _build_capital_gap_summary(
        layer4_scenarios=layer4_scenarios,
        available_capital=economic_settings.available_capital,
    )
    layer4_contract = _build_layer4_contract_summary(layer4_scenarios)
    layer4_aggregate_deltas = _build_layer4_aggregate_deltas(layer4_scenarios)
    layer5_intervention = _build_layer5_intervention_signals(
        risk_level=risk_level,
        layer4_scenarios=layer4_scenarios,
        in_flight_effective_qty_total=in_flight_effective_qty_total,
        unavoidable_stockout_risk_threshold=(
            layer_proxy_settings.layer5_unavoidable_stockout_risk_threshold
        ),
        accelerate_production_risk_threshold=(
            layer_proxy_settings.layer5_accelerate_production_risk_threshold
        ),
        accelerate_action_cost_rate=layer_proxy_settings.layer5_accelerate_action_cost_rate,
        price_slowdown_lost_volume_rate=layer_proxy_settings.layer5_price_slowdown_lost_volume_rate,
        reduce_order_marginal_profit_rate=layer_proxy_settings.layer5_reduce_order_marginal_profit_rate,
    )
    layer5_contract = _build_layer5_contract_summary(
        layer5_intervention=layer5_intervention,
        unavoidable_stockout_risk_threshold=(
            layer_proxy_settings.layer5_unavoidable_stockout_risk_threshold
        ),
        accelerate_production_risk_threshold=(
            layer_proxy_settings.layer5_accelerate_production_risk_threshold
        ),
        reduce_order_marginal_profit_rate=(
            layer_proxy_settings.layer5_reduce_order_marginal_profit_rate
        ),
    )
    layer5_intervention_meta = {
        **layer5_intervention,
        "contract": layer5_contract,
    }
    action = _choose_action(
        risk_level=risk_level,
        candidate_units=candidate_total_units,
        allow_order_with_buffer=settings.allow_order_with_buffer,
    )

    if action == "wait":
        recommendation = ProductionOrderRecommendation(
            action="wait",
            priority=settings.priority,
            target_arrival_date=(now + timedelta(days=settings.lead_time_days_total)).date(),
            total_units=0,
            lines=[],
        )
    else:
        recommendation = ProductionOrderRecommendation(
            action=action,
            priority=settings.priority,
            target_arrival_date=(now + timedelta(days=settings.lead_time_days_total)).date(),
            total_units=candidate_total_units,
            lines=candidate_lines,
        )

    alternatives = _build_alternatives(action)

    elastic_uplift_line_keys_items = [
        {
            "color_id": color_id,
            "size_id": size_id,
        }
        for color_id, size_id in elastic_uplift_keys
    ]
    elastic_uplift_line_alloc_items = [
        {
            "color_id": color_id,
            "size_id": size_id,
            "qty": qty,
        }
        for (color_id, size_id), qty in sorted(elastic_uplift_line_alloc.items(), key=lambda item: item[0])
    ]
    layer4_scenario_factor_items = [
        {
            "scenario": scenario_name,
            "factor": factor,
        }
        for scenario_name, factor in LAYER4_SCENARIO_FACTORS
    ]

    explanation = ProductionOrderExplanationBlock(
        summary=(
            f"Риск {risk_level}: оценка покрытия {days_of_cover_estimate:.1f} дней при reorder point "
            f"{reorder_point_days} дней (lead_time={settings.lead_time_days_total}, "
            f"safety_stock={settings.safety_stock_days})."
        ),
        steps=[
            (
                f"Спрос по наборам: total_daily_sales={total_daily_sales:.3f}, "
                f"planning_horizon_days={request.planning_horizon_days}, "
                f"expected_horizon_sales={expected_horizon_sales:.1f}."
            ),
            (
                f"Учтены ready stock наборов (WB+локальный)={ready_bundle_stock_total} и "
                f"оценка сырьевого потенциала={competition_raw_bundle_stock} "
                f"(competition-aware by bundle: {competition_raw_breakdown})."
            ),
            (
                f"Дефицит по модели B: target_bundle_units={required_bundle_units}, "
                f"bundle_deficit_total={bundle_deficit_total}, распределение через size_weights."
            ),
            (
                f"Reorder policy: lead_time_days={settings.lead_time_days_total}, "
                f"safety_stock_days={settings.safety_stock_days}, reorder_point_days={reorder_point_days}."
            ),
            (
                f"Economic buffer policy: enabled={settings.allow_order_with_buffer}, "
                f"economic_buffer_days={economic_buffer_days}, target_horizon_days={target_bundle_horizon_days}."
            ),
            (
                f"Источник параметров: size_weights={size_weights_source}, "
                f"in_flight={in_flight_source}, bundle_stock={bundle_stock_source}."
            ),
            (
                "Economics trust: "
                f"level={economics_trust['economics_trust_level']}, "
                "code_default_key_fields="
                f"{economics_trust['code_default_key_fields']}, "
                "code_default_key_fields_count="
                f"{economics_trust['code_default_key_fields_count']}, "
                "code_default_dominance_ratio="
                f"{economics_trust['code_default_dominance_ratio']}, "
                f"warnings={economics_warnings}."
            ),
            (
                "Assorti classification: "
                f"source={ASSORTI_CLASSIFICATION_SOURCE}, "
                f"fallback_admin_ids={sorted(admin_assorti_bundle_type_ids)}, "
                f"fallback_global_ids={sorted(global_assorti_bundle_type_ids)}, "
                f"assorti_bundle_types={assorti_bundle_type_count}, "
                f"main_bundle_types={main_bundle_type_count}, "
                f"source_breakdown={assorti_classification_source_breakdown}."
            ),
            (
                f"Layer 1 stock health: sku_count={len(layer1_stock_health_metrics)}, "
                f"avg_coverage_days={layer1_avg_coverage_days}, "
                f"high_stockout_risk_skus={layer1_high_stockout_risk_count}, "
                f"high_stockout_threshold={LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD}, "
                f"contract_status={layer1_contract['status']}."
            ),
            (
                f"Layer 2 allocation: method={LAYER2_ALLOCATION_METHOD_CANONICAL}, "
                f"legacy_method={LAYER2_ALLOCATION_METHOD}, "
                f"decision_gate={LAYER2_DECISION_GATE_CANONICAL}, "
                f"legacy_decision_gate={LAYER2_DECISION_GATE_LEGACY}, "
                "tie_break=hold, "
                f"main={layer2_allocation_summary['main']}, "
                f"assorti={layer2_allocation_summary['assorti']}, "
                f"hold={layer2_allocation_summary['hold']}, "
                f"near_tie={layer2_decision_quality['near_tie_count']}, "
                f"tie_count={layer2_decision_quality['tie_count']}, "
                "reason_counts="
                f"{layer2_decision_quality['decision_reason_counts']}, "
                "objective_reason_counts="
                f"{layer2_decision_quality['decision_reason_counts_objective_score']}, "
                "avg_profit_gap_until_eta="
                f"{layer2_decision_quality['avg_profit_gap_until_eta']}, "
                "avg_objective_score_gap_until_eta="
                f"{layer2_decision_quality['avg_objective_score_gap_until_eta']}, "
                "capital_locked_total="
                f"{layer2_decision_quality['capital_locked_total']}, "
                f"contract_status={layer2_contract['status']}."
            ),
            (
                "Layer 3 purchase shaping: method=allocation_decision_factors, "
                f"qty_before={layer3_purchase_shaping['qty_before']}, "
                f"qty_after_base={layer3_purchase_shaping['qty_after_base']}, "
                f"qty_after={layer3_purchase_shaping['qty_after']}, "
                f"adjusted_lines={layer3_purchase_shaping['adjusted_lines']}, "
                f"calibration_delta_vs_base={layer3_purchase_shaping['qty_delta_vs_base']}, "
                f"contract_status={layer3_contract['status']}, "
                "decision_lines="
                f"main:{layer3_purchase_shaping['main_lines']}|"
                f"assorti:{layer3_purchase_shaping['assorti_lines']}|"
                f"hold:{layer3_purchase_shaping['hold_lines']}."
            ),
            (
                "Layer 4 scenarios: "
                f"Conservative(capital={layer4_scenarios[0]['total_capital_required']},gross_profit={layer4_scenarios[0]['expected_gross_profit']},objective={layer4_scenarios[0]['objective_score']},risk={layer4_scenarios[0]['stockout_risk_proxy']}), "
                f"Balanced(capital={layer4_scenarios[1]['total_capital_required']},gross_profit={layer4_scenarios[1]['expected_gross_profit']},objective={layer4_scenarios[1]['objective_score']},risk={layer4_scenarios[1]['stockout_risk_proxy']}), "
                f"Aggressive(capital={layer4_scenarios[2]['total_capital_required']},gross_profit={layer4_scenarios[2]['expected_gross_profit']},objective={layer4_scenarios[2]['objective_score']},risk={layer4_scenarios[2]['stockout_risk_proxy']})."
            ),
            (
                "Layer 4 contract: "
                f"version={layer4_contract['version']}, "
                f"status={layer4_contract['status']}, "
                f"order_matches_expected={layer4_contract['order_matches_expected']}, "
                f"checks={layer4_contract['checks']}."
            ),
            (
                "Layer 4 aggregate deltas: "
                "aggressive_vs_conservative("
                "capital_delta="
                f"{layer4_aggregate_deltas['aggressive_vs_conservative']['capital_delta']},"
                "gross_profit_delta="
                f"{layer4_aggregate_deltas['aggressive_vs_conservative']['gross_profit_delta']},"
                "objective_delta="
                f"{layer4_aggregate_deltas['aggressive_vs_conservative']['objective_delta']})."
            ),
            (
                "Capital gap: "
                f"status={capital_gap_summary['status']}, "
                f"available_capital={capital_gap_summary['available_capital']}, "
                f"required_capital={capital_gap_summary['required_capital']}, "
                f"deficit_or_surplus={capital_gap_summary['deficit_or_surplus']}."
            ),
            (
                "Capital constraint: "
                f"status={capital_constraint_summary['status']}, "
                f"constrained={capital_constraint_summary['constrained']}, "
                f"available_capital={capital_constraint_summary['available_capital']}, "
                "required_capital_before_constraint="
                f"{capital_constraint_summary['required_capital_before_constraint']}, "
                "allocated_capital_after_constraint="
                f"{capital_constraint_summary['allocated_capital_after_constraint']}, "
                f"cutoff_line={capital_constraint_summary['cutoff_line']}, "
                f"contract_status={capital_constraint_contract['status']}."
            ),
            (
                "Layer 5 intervention: "
                f"unavoidable_stockout={layer5_intervention['unavoidable_stockout']}, "
                f"signals={layer5_intervention['signals']}, "
                f"reason={layer5_intervention['reason']}, "
                "aggressive_stockout_risk="
                f"{layer5_intervention['aggressive_stockout_risk_proxy']}, "
                f"threshold={layer5_intervention['risk_threshold']}, "
                f"signal_thresholds={layer5_intervention['signal_thresholds']}, "
                "economic_justification="
                f"{layer5_intervention.get('economic_justification', {})}, "
                f"contract_status={layer5_contract['status']}."
            ),
            (
                f"Elastic scope: mode={elastic_scope_mode}, "
                f"applicable_types={sorted(applicable_elastic_type_ids)}, "
                f"scoped_settings={len(scoped_elastic_rows)}, "
                f"scoped_lines={len(elastic_scope_line_keys)}."
            ),
            (
                f"Elastic uplift: delta={elastic_uplift_delta}, "
                f"scope={elastic_uplift_scope}, "
                f"affected_lines={len(elastic_uplift_keys)}, "
                f"line_keys={elastic_uplift_keys}, "
                f"line_alloc={elastic_uplift_line_alloc}."
            ),
            (
                f"In-flight вклад (ETA/stage): raw_qty={in_flight_raw_qty_total}, "
                f"effective_qty={in_flight_effective_qty_total}, lines={in_flight_effective_lines}."
            ),
            (
                f"Применены ограничения: fabric_constraints={len(constraints_applied.fabric_min_batches)}, "
                f"elastic_constraints={len(constraints_applied.elastic_min_batches)}."
            ),
        ],
        meta={
            "warnings": economics_warnings,
            "economics_trust": economics_trust,
            "sources": {
                "size_weights": size_weights_source,
                "in_flight": in_flight_source,
                "bundle_stock": bundle_stock_source,
            },
            "reorder_policy": {
                "lead_time_days_total": settings.lead_time_days_total,
                "safety_stock_days": settings.safety_stock_days,
                "reorder_point_days": reorder_point_days,
            },
            "layer_1_stock_health": {
                "metrics": layer1_stock_health_metrics,
                "summary": {
                    "sku_count": len(layer1_stock_health_metrics),
                    "avg_coverage_days": layer1_avg_coverage_days,
                    "high_stockout_risk_skus": layer1_high_stockout_risk_count,
                    "high_stockout_risk_threshold": LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD,
                },
                "contract": layer1_contract,
                "assorti_classification": {
                    "source": ASSORTI_CLASSIFICATION_SOURCE,
                    "fallback_sources": [
                        ASSORTI_CLASSIFICATION_ADMIN_FALLBACK_SOURCE,
                        ASSORTI_CLASSIFICATION_GLOBAL_FALLBACK_SOURCE,
                    ],
                    "fallback_mapping": {
                        "admin_defaults_bundle_type_ids": sorted(admin_assorti_bundle_type_ids),
                        "global_default_bundle_type_ids": sorted(global_assorti_bundle_type_ids),
                    },
                    "source_breakdown": assorti_classification_source_breakdown,
                    "summary": {
                        "assorti_bundle_types": assorti_bundle_type_count,
                        "main_bundle_types": main_bundle_type_count,
                    },
                    "bundle_types": assorti_classification_by_bundle_type,
                },
                "proxies": {
                    "main_margin": economic_settings.margin_main_per_unit,
                    "assorti_margin": economic_settings.margin_assorti_per_unit,
                    "unit_capital": economic_settings.unit_capital_per_unit,
                },
            },
            "layer_2_allocation": {
                "method": LAYER2_ALLOCATION_METHOD_CANONICAL,
                "method_canonical": LAYER2_ALLOCATION_METHOD_CANONICAL,
                "legacy_method": LAYER2_ALLOCATION_METHOD,
                "legacy_alias_deprecation_plan": _build_layer2_legacy_alias_deprecation_plan(),
                "decisions": layer2_allocation_decisions,
                "summary": layer2_allocation_summary,
                "contract": layer2_contract,
                "decision_quality": layer2_decision_quality,
                "decision_gate": LAYER2_DECISION_GATE_CANONICAL,
                "decision_gate_canonical": LAYER2_DECISION_GATE_CANONICAL,
                "legacy_decision_gate": LAYER2_DECISION_GATE_LEGACY,
                "tie_break": "hold",
                "gmroi_usage": "diagnostic_only",
                "objective_formula": (
                    "expected_gross_profit_until_eta"
                    "-capital_cost_penalty"
                    "-stockout_penalty"
                    "-overstock_penalty"
                ),
                "objective_parameters": {
                    "capital_cost_rate": layer_proxy_settings.layer2_capital_cost_rate,
                    "stockout_penalty_weight": layer_proxy_settings.layer2_stockout_penalty_weight,
                    "overstock_penalty_weight": layer_proxy_settings.layer2_overstock_penalty_weight,
                },
                "objective_source": {
                    "capital_cost_rate": layer_proxy_settings.source.get("layer2_capital_cost_rate"),
                    "stockout_penalty_weight": layer_proxy_settings.source.get(
                        "layer2_stockout_penalty_weight"
                    ),
                    "overstock_penalty_weight": layer_proxy_settings.source.get(
                        "layer2_overstock_penalty_weight"
                    ),
                },
            },
            "layer_3_purchase_shaping": {
                "method": "allocation_decision_factors",
                "factors": LAYER3_PURCHASE_FACTOR_BY_DECISION,
                "contract": layer3_contract,
                **layer3_purchase_shaping,
            },
            "layer_4_scenarios": {
                "method": "deterministic_factor_scenarios",
                "factors": layer4_scenario_factor_items,
                "contract": layer4_contract,
                "aggregate_deltas": layer4_aggregate_deltas,
                "scenarios": layer4_scenarios,
            },
            "layer_5_intervention": layer5_intervention_meta,
            "capital_gap": capital_gap_summary,
            "capital_constraint": capital_constraint_summary,
            "alpha_proxy_economics": {
                "source": LAYER_PROXY_VALUE_SOURCE,
                "calibration_state": "alpha_proxy_not_calibrated",
                "economics_formula_version": ECONOMICS_FORMULA_VERSION,
                "economic_calibration_state": economic_settings.calibration_state,
                "economics_trust_level": economics_trust.get("economics_trust_level"),
                "economics_trust": economics_trust,
                "layer_1_high_stockout_risk_threshold": LAYER1_HIGH_STOCKOUT_RISK_THRESHOLD,
                "layer_2_allocation_method": LAYER2_ALLOCATION_METHOD_CANONICAL,
                "layer_2_allocation_method_canonical": LAYER2_ALLOCATION_METHOD_CANONICAL,
                "layer_2_legacy_allocation_method": LAYER2_ALLOCATION_METHOD,
                "layer_2_decision_gate": LAYER2_DECISION_GATE_CANONICAL,
                "layer_2_decision_gate_canonical": LAYER2_DECISION_GATE_CANONICAL,
                "layer_2_legacy_decision_gate": LAYER2_DECISION_GATE_LEGACY,
                "layer_2_legacy_alias_deprecation_plan": _build_layer2_legacy_alias_deprecation_plan(),
                "layer_2_near_tie_objective_gap_threshold": LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD,
                "layer_2_near_tie_profit_gap_threshold": LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD,
                "layer_2_objective_parameters": {
                    "capital_cost_rate": layer_proxy_settings.layer2_capital_cost_rate,
                    "stockout_penalty_weight": layer_proxy_settings.layer2_stockout_penalty_weight,
                    "overstock_penalty_weight": layer_proxy_settings.layer2_overstock_penalty_weight,
                },
                "margin_proxy": {
                    "main": economic_settings.margin_main_per_unit,
                    "assorti": economic_settings.margin_assorti_per_unit,
                },
                "unit_capital_proxy": economic_settings.unit_capital_per_unit,
                "economic_inputs": {
                    "production_cost_per_unit": economic_settings.production_cost_per_unit,
                    "logistics_cost_per_unit": economic_settings.logistics_cost_per_unit,
                    "wb_commission_percent_main": economic_settings.wb_commission_percent_main,
                    "wb_commission_percent_assorti": economic_settings.wb_commission_percent_assorti,
                    "average_realized_price_main": economic_settings.average_realized_price_main,
                    "average_realized_price_assorti": economic_settings.average_realized_price_assorti,
                    "available_capital": economic_settings.available_capital,
                },
                "economic_source": economic_settings.source,
                "layer_3_purchase_factors": LAYER3_PURCHASE_FACTOR_BY_DECISION,
                "layer_3_calibration": {
                    "method": LAYER3_CALIBRATION_METHOD,
                    "stockout_boost_max": layer_proxy_settings.layer3_stockout_boost_max,
                    "overstock_dampen_max": layer_proxy_settings.layer3_overstock_dampen_max,
                    "stockout_weight_by_decision": LAYER3_STOCKOUT_WEIGHT_BY_DECISION,
                    "overstock_weight_by_decision": LAYER3_OVERSTOCK_WEIGHT_BY_DECISION,
                    "factor_bounds": {
                        decision: {
                            "min": bounds[0],
                            "max": bounds[1],
                        }
                        for decision, bounds in LAYER3_FACTOR_BOUNDS.items()
                    },
                },
                "layer_proxy_source": layer_proxy_settings.source,
                "layer5_threshold_order_adjusted": layer_proxy_settings.threshold_order_adjusted,
                "layer_4_scenario_factors": layer4_scenario_factor_items,
                "layer_4_contract_version": LAYER4_CONTRACT_VERSION,
                "layer_5_unavoidable_stockout_risk_threshold": (
                    layer_proxy_settings.layer5_unavoidable_stockout_risk_threshold
                ),
                "layer_5_signal_thresholds": {
                    "accelerate_production": (
                        layer_proxy_settings.layer5_accelerate_production_risk_threshold
                    ),
                    "increase_price_to_slow_velocity": (
                        layer_proxy_settings.layer5_unavoidable_stockout_risk_threshold
                    ),
                    "reduce_order_size": layer_proxy_settings.layer5_reduce_order_marginal_profit_rate,
                },
                "layer_5_cost_policy_parameters": {
                    "accelerate_action_cost_rate": (
                        layer_proxy_settings.layer5_accelerate_action_cost_rate
                    ),
                    "price_slowdown_lost_volume_rate": (
                        layer_proxy_settings.layer5_price_slowdown_lost_volume_rate
                    ),
                    "reduce_order_marginal_profit_rate": (
                        layer_proxy_settings.layer5_reduce_order_marginal_profit_rate
                    ),
                },
            },
            "economic_buffer": {
                "enabled": settings.allow_order_with_buffer,
                "days": economic_buffer_days,
                "target_horizon_days": target_bundle_horizon_days,
            },
            "in_flight_effective": {
                "raw_qty": in_flight_raw_qty_total,
                "effective_qty": in_flight_effective_qty_total,
                "lines": in_flight_effective_lines,
            },
            "elastic_scope": {
                "mode": elastic_scope_mode,
                "applicable_types": sorted(applicable_elastic_type_ids),
                "scoped_settings": len(scoped_elastic_rows),
                "scoped_lines": len(elastic_scope_line_keys),
            },
            "elastic_uplift": {
                "delta": elastic_uplift_delta,
                "scope": elastic_uplift_scope,
                "affected_lines": len(elastic_uplift_keys),
                "line_keys": elastic_uplift_line_keys_items,
                "line_alloc": elastic_uplift_line_alloc_items,
            },
        },
    )
    explanation = _apply_explainability_mode(
        explanation=explanation,
        mode=request.explainability_mode,
    )

    return ProductionOrderProposalResponse(
        status="ok",
        article_id=request.article_id,
        generated_at=now,
        risk_level=risk_level,
        days_of_cover_estimate=float(days_of_cover_estimate),
        lead_time_days_total=settings.lead_time_days_total,
        recommendation=recommendation,
        constraints_applied=constraints_applied,
        alternatives=alternatives,
        explanation=explanation,
    )
