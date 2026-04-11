from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _AlphaProxyApplicationResult:
    layer4_scenario_factor_items: list[dict[str, object]]
    alpha_proxy_economics: dict[str, object]


def _apply_production_order_alpha_proxy_economics(
    *,
    layer4_scenario_factors: list[tuple[str, float]],
    layer_proxy_value_source: str,
    economics_formula_version: str,
    economic_calibration_state: str,
    economics_trust: dict[str, object],
    capital_governance: dict[str, object],
    layer1_high_stockout_risk_threshold: float,
    layer2_allocation_method: str,
    layer2_allocation_method_canonical: str,
    layer2_legacy_allocation_method: str,
    layer2_decision_gate: str,
    layer2_decision_gate_canonical: str,
    layer2_legacy_decision_gate: str,
    layer2_near_tie_objective_gap_threshold: float,
    layer2_near_tie_profit_gap_threshold: float,
    layer2_objective_parameters: dict[str, object],
    main_margin_proxy: float,
    assorti_margin_proxy: float,
    unit_capital_proxy: float,
    economic_inputs: dict[str, object],
    economic_source: dict[str, object],
    layer3_purchase_factors: dict[str, object],
    layer3_calibration_method: str,
    layer3_stockout_boost_max: float,
    layer3_overstock_dampen_max: float,
    layer3_stockout_weight_by_decision: dict[str, object],
    layer3_overstock_weight_by_decision: dict[str, object],
    layer3_factor_bounds: dict[str, tuple[float, float]],
    layer_proxy_source: dict[str, object],
    layer5_threshold_order_adjusted: bool,
    layer4_contract_version: str,
    layer5_unavoidable_stockout_risk_threshold: float,
    layer5_accelerate_production_risk_threshold: float,
    layer5_accelerate_action_cost_rate: float,
    layer5_price_slowdown_lost_volume_rate: float,
    layer5_reduce_order_marginal_profit_rate: float,
    build_layer2_legacy_alias_deprecation_plan: Callable[[], dict[str, object]],
    build_alpha_proxy_economics_meta: Callable[..., dict[str, object]],
) -> _AlphaProxyApplicationResult:
    layer4_scenario_factor_items = [
        {
            "scenario": scenario_name,
            "factor": factor,
        }
        for scenario_name, factor in layer4_scenario_factors
    ]
    alpha_proxy_economics = build_alpha_proxy_economics_meta(
        layer_proxy_value_source=layer_proxy_value_source,
        economics_formula_version=economics_formula_version,
        economic_calibration_state=economic_calibration_state,
        economics_trust=economics_trust,
        capital_governance=capital_governance,
        layer1_high_stockout_risk_threshold=layer1_high_stockout_risk_threshold,
        layer2_allocation_method=layer2_allocation_method,
        layer2_allocation_method_canonical=layer2_allocation_method_canonical,
        layer2_legacy_allocation_method=layer2_legacy_allocation_method,
        layer2_decision_gate=layer2_decision_gate,
        layer2_decision_gate_canonical=layer2_decision_gate_canonical,
        layer2_legacy_decision_gate=layer2_legacy_decision_gate,
        layer2_legacy_alias_deprecation_plan=build_layer2_legacy_alias_deprecation_plan(),
        layer2_near_tie_objective_gap_threshold=layer2_near_tie_objective_gap_threshold,
        layer2_near_tie_profit_gap_threshold=layer2_near_tie_profit_gap_threshold,
        layer2_objective_parameters=layer2_objective_parameters,
        main_margin_proxy=main_margin_proxy,
        assorti_margin_proxy=assorti_margin_proxy,
        unit_capital_proxy=unit_capital_proxy,
        economic_inputs=economic_inputs,
        economic_source=economic_source,
        layer3_purchase_factors=layer3_purchase_factors,
        layer3_calibration_method=layer3_calibration_method,
        layer3_stockout_boost_max=layer3_stockout_boost_max,
        layer3_overstock_dampen_max=layer3_overstock_dampen_max,
        layer3_stockout_weight_by_decision=layer3_stockout_weight_by_decision,
        layer3_overstock_weight_by_decision=layer3_overstock_weight_by_decision,
        layer3_factor_bounds=layer3_factor_bounds,
        layer_proxy_source=layer_proxy_source,
        layer5_threshold_order_adjusted=layer5_threshold_order_adjusted,
        layer4_scenario_factors=layer4_scenario_factor_items,
        layer4_contract_version=layer4_contract_version,
        layer5_unavoidable_stockout_risk_threshold=layer5_unavoidable_stockout_risk_threshold,
        layer5_accelerate_production_risk_threshold=layer5_accelerate_production_risk_threshold,
        layer5_accelerate_action_cost_rate=layer5_accelerate_action_cost_rate,
        layer5_price_slowdown_lost_volume_rate=layer5_price_slowdown_lost_volume_rate,
        layer5_reduce_order_marginal_profit_rate=layer5_reduce_order_marginal_profit_rate,
    )
    return _AlphaProxyApplicationResult(
        layer4_scenario_factor_items=layer4_scenario_factor_items,
        alpha_proxy_economics=alpha_proxy_economics,
    )
