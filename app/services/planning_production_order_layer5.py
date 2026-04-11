from __future__ import annotations

from app.services.planning_production_order_capital import _bounded_unit_float
from app.services.planning_production_order_layer_proxy import (
    LAYER5_ACCELERATE_ACTION_COST_RATE,
    LAYER5_ACCELERATE_PRODUCTION_RISK_THRESHOLD,
    LAYER5_PRICE_SLOWDOWN_LOST_VOLUME_RATE,
    LAYER5_REDUCE_ORDER_MARGINAL_PROFIT_RATE,
    LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD,
)

LAYER5_CONTRACT_VERSION = "v1_alpha"
LAYER5_PRICE_SLOWDOWN_RISK_THRESHOLD = LAYER5_UNAVOIDABLE_STOCKOUT_RISK_THRESHOLD


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


def _build_layer5_threshold_clamped_warning(
    *,
    article_id: int,
    accelerate_threshold_effective: float,
    unavoidable_threshold_effective: float,
    effective_source: object,
) -> dict[str, object]:
    return {
        "code": "layer5_accelerate_threshold_clamped_to_unavoidable",
        "severity": "MEDIUM",
        "message": (
            "layer5_accelerate_production_risk_threshold was below "
            "layer5_unavoidable_stockout_risk_threshold and was clamped upward at runtime"
        ),
        "article_id": int(article_id),
        "field": "layer5_accelerate_production_risk_threshold",
        "field_metadata": {
            "description": "Layer 5 accelerate-production risk threshold input",
            "type": "number",
        },
        "threshold_order_adjusted": True,
        "accelerate_threshold_effective": round(float(accelerate_threshold_effective), 4),
        "unavoidable_threshold_effective": round(float(unavoidable_threshold_effective), 4),
        "effective_source": effective_source,
        "action": (
            "Review Layer 5 threshold inputs; accelerate threshold cannot be lower than unavoidable "
            "stockout threshold."
        ),
        "next_steps": ["review_layer5_threshold_configuration"],
    }
