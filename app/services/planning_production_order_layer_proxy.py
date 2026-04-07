from __future__ import annotations

from dataclasses import dataclass

from app.models.models import ArticlePlanningSettings, GlobalPlanningSettings
from app.schemas.planning_production_order import PlanningOverridesInput
from app.services.planning_production_order_economics import LAYER_PROXY_VALUE_SOURCE

LAYER2_CAPITAL_COST_RATE = 0.08
LAYER2_STOCKOUT_PENALTY_WEIGHT = 1.0
LAYER2_OVERSTOCK_PENALTY_WEIGHT = 1.0
LAYER3_STOCKOUT_BOOST_MAX = 0.30
LAYER3_OVERSTOCK_DAMPEN_MAX = 0.40
LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD = 0.25
LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD = 0.35
LAYER5_ACCELERATE_ACTION_COST_RATE = 0.20
LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE = 0.15
LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE = 0.10


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
    invalid_values_ignored: list[dict[str, object]]


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


def _resolve_layer_proxy_float(
    *,
    field_name: str | None,
    request_value: float | None,
    admin_value: float | None,
    global_value: float | None,
    code_default: float,
) -> tuple[float, str, list[dict[str, object]]]:
    ignored_values: list[dict[str, object]] = []

    def _serialize_invalid_value(value: object) -> object:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return round(float(value), 4)
        return value

    def _record_invalid(source: str, raw_value: object) -> None:
        if field_name is None:
            return
        ignored_values.append(
            {
                "field": field_name,
                "invalid_source": source,
                "invalid_value": _serialize_invalid_value(raw_value),
            }
        )

    def _finalize(effective_value: float, effective_source: str) -> tuple[float, str, list[dict[str, object]]]:
        if not ignored_values:
            return effective_value, effective_source, []
        effective_value_rounded = round(float(effective_value), 4)
        return (
            effective_value,
            effective_source,
            [
                {
                    **item,
                    "effective_source": effective_source,
                    "effective_value": effective_value_rounded,
                }
                for item in ignored_values
            ],
        )

    request_normalized = _normalize_unit_interval(request_value)
    if request_normalized is not None:
        return request_normalized, "request", []
    if request_value is not None:
        _record_invalid("request", request_value)

    admin_normalized = _normalize_unit_interval(admin_value)
    if admin_normalized is not None:
        return _finalize(admin_normalized, "admin_defaults")
    if admin_value is not None:
        _record_invalid("admin_defaults", admin_value)

    global_normalized = _normalize_unit_interval(global_value)
    if global_normalized is not None:
        return _finalize(global_normalized, "global_default")
    if global_value is not None:
        _record_invalid("global_default", global_value)

    return _finalize(float(code_default), LAYER_PROXY_VALUE_SOURCE)


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

    invalid_values_ignored: list[dict[str, object]] = []

    layer3_stockout_boost_max, layer3_stockout_source, layer3_stockout_invalid = _resolve_layer_proxy_float(
        request_value=request_layer3_stockout_boost,
        admin_value=admin_layer3_stockout_boost,
        global_value=global_layer3_stockout_boost,
        code_default=LAYER3_STOCKOUT_BOOST_MAX,
        field_name="layer3_stockout_boost_max",
    )
    invalid_values_ignored.extend(layer3_stockout_invalid)
    layer3_overstock_dampen_max, layer3_overstock_source, layer3_overstock_invalid = _resolve_layer_proxy_float(
        request_value=request_layer3_overstock_dampen,
        admin_value=admin_layer3_overstock_dampen,
        global_value=global_layer3_overstock_dampen,
        code_default=LAYER3_OVERSTOCK_DAMPEN_MAX,
        field_name="layer3_overstock_dampen_max",
    )
    invalid_values_ignored.extend(layer3_overstock_invalid)
    layer5_unavoidable_threshold, layer5_unavoidable_source, layer5_unavoidable_invalid = _resolve_layer_proxy_float(
        request_value=request_layer5_unavoidable_threshold,
        admin_value=admin_layer5_unavoidable_threshold,
        global_value=global_layer5_unavoidable_threshold,
        code_default=LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
        field_name="layer5_unavoidable_stockout_risk_threshold",
    )
    invalid_values_ignored.extend(layer5_unavoidable_invalid)
    layer5_accelerate_threshold, layer5_accelerate_source, layer5_accelerate_invalid = _resolve_layer_proxy_float(
        request_value=request_layer5_accelerate_threshold,
        admin_value=admin_layer5_accelerate_threshold,
        global_value=global_layer5_accelerate_threshold,
        code_default=LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
        field_name="layer5_accelerate_production_risk_threshold",
    )
    invalid_values_ignored.extend(layer5_accelerate_invalid)
    layer2_capital_cost_rate, layer2_capital_cost_rate_source, _ = _resolve_layer_proxy_float(
        request_value=request_layer2_capital_cost_rate,
        admin_value=admin_layer2_capital_cost_rate,
        global_value=global_layer2_capital_cost_rate,
        code_default=LAYER2_CAPITAL_COST_RATE,
        field_name=None,
    )
    layer2_stockout_penalty_weight, layer2_stockout_penalty_weight_source, _ = _resolve_layer_proxy_float(
        request_value=request_layer2_stockout_penalty_weight,
        admin_value=admin_layer2_stockout_penalty_weight,
        global_value=global_layer2_stockout_penalty_weight,
        code_default=LAYER2_STOCKOUT_PENALTY_WEIGHT,
        field_name=None,
    )
    layer2_overstock_penalty_weight, layer2_overstock_penalty_weight_source, _ = _resolve_layer_proxy_float(
        request_value=request_layer2_overstock_penalty_weight,
        admin_value=admin_layer2_overstock_penalty_weight,
        global_value=global_layer2_overstock_penalty_weight,
        code_default=LAYER2_OVERSTOCK_PENALTY_WEIGHT,
        field_name=None,
    )
    layer5_accelerate_action_cost_rate, layer5_accelerate_action_cost_rate_source, _ = _resolve_layer_proxy_float(
        request_value=request_layer5_accelerate_action_cost_rate,
        admin_value=admin_layer5_accelerate_action_cost_rate,
        global_value=global_layer5_accelerate_action_cost_rate,
        code_default=LAYER5_ACCELERATE_ACTION_COST_RATE,
        field_name=None,
    )
    (
        layer5_price_slowdown_lost_volume_rate,
        layer5_price_slowdown_lost_volume_rate_source,
        _,
    ) = _resolve_layer_proxy_float(
        request_value=request_layer5_price_slowdown_lost_volume_rate,
        admin_value=admin_layer5_price_slowdown_lost_volume_rate,
        global_value=global_layer5_price_slowdown_lost_volume_rate,
        code_default=LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE,
        field_name=None,
    )
    (
        layer5_reduce_order_marginal_profit_rate,
        layer5_reduce_order_marginal_profit_rate_source,
        _,
    ) = _resolve_layer_proxy_float(
        request_value=request_layer5_reduce_order_marginal_profit_rate,
        admin_value=admin_layer5_reduce_order_marginal_profit_rate,
        global_value=global_layer5_reduce_order_marginal_profit_rate,
        code_default=LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
        field_name=None,
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
        invalid_values_ignored=invalid_values_ignored,
    )
