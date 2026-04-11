from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from app.schemas.planning_production_order import ProductionOrderExplanationBlock

EXPLAINABILITY_MODE_COMPACT = "compact"


def _compact_explanation_steps(steps: list[str]) -> tuple[list[str], int]:
    if not steps:
        return [], 0

    keep_tokens = (
        "WB ingestion adapter",
        "Спрос по наборам",
        "Источник параметров",
        "Economics trust",
        "Assorti classification",
        "Physical scope",
        "Resource allocation",
        "Arrival projection",
        "Shared color pool",
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

    compact_steps = compact_steps[:14]
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


def _build_explanation_warnings(
    *,
    economics_warnings: list[dict[str, object]],
    article_id: int,
    invalid_values_ignored: dict[str, object],
    threshold_order_adjusted: bool,
    accelerate_threshold_effective: float,
    unavoidable_threshold_effective: float,
    threshold_effective_source: str | None,
    arrival_projection_status: str,
    action: str,
    capital_constraint_summary: dict[str, object],
    projected_shortage_before_arrival: int,
    available_capital_effective: float,
    build_layer_proxy_invalid_values_ignored_warning: Callable[..., dict[str, object]],
    build_layer5_threshold_clamped_warning: Callable[..., dict[str, object]],
    build_shortage_wait_blocked_by_capital_constraint_warning: Callable[..., dict[str, object]],
) -> list[dict[str, object]]:
    explanation_warnings = list(economics_warnings)
    if invalid_values_ignored:
        explanation_warnings.append(
            build_layer_proxy_invalid_values_ignored_warning(
                article_id=article_id,
                invalid_values_ignored=invalid_values_ignored,
            )
        )
    if threshold_order_adjusted:
        explanation_warnings.append(
            build_layer5_threshold_clamped_warning(
                article_id=article_id,
                accelerate_threshold_effective=accelerate_threshold_effective,
                unavoidable_threshold_effective=unavoidable_threshold_effective,
                effective_source=threshold_effective_source,
            )
        )

    shortage_wait_blocked = (
        arrival_projection_status == "shortage_before_arrival"
        and action == "wait"
        and str(capital_constraint_summary.get("status")) == "budget_limited_applied"
        and bool(capital_constraint_summary.get("constrained"))
        and int(capital_constraint_summary.get("line_count_before", 0) or 0) > 0
        and int(capital_constraint_summary.get("line_count_after", 0) or 0) == 0
    )
    if shortage_wait_blocked:
        explanation_warnings.append(
            build_shortage_wait_blocked_by_capital_constraint_warning(
                article_id=article_id,
                projected_shortage_before_arrival=projected_shortage_before_arrival,
                capital_constraint_summary=capital_constraint_summary,
                available_capital_effective=available_capital_effective,
            )
        )

    return explanation_warnings


def _build_alpha_proxy_economics_meta(
    *,
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
    layer2_legacy_alias_deprecation_plan: dict[str, object],
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
    layer4_scenario_factors: list[dict[str, object]],
    layer4_contract_version: str,
    layer5_unavoidable_stockout_risk_threshold: float,
    layer5_accelerate_production_risk_threshold: float,
    layer5_accelerate_action_cost_rate: float,
    layer5_price_slowdown_lost_volume_rate: float,
    layer5_reduce_order_marginal_profit_rate: float,
) -> dict[str, object]:
    return {
        "source": layer_proxy_value_source,
        "calibration_state": "alpha_proxy_not_calibrated",
        "economics_formula_version": economics_formula_version,
        "economic_calibration_state": economic_calibration_state,
        "economics_trust_level": economics_trust.get("economics_trust_level"),
        "economics_trust": economics_trust,
        "capital_governance": capital_governance,
        "layer_1_high_stockout_risk_threshold": layer1_high_stockout_risk_threshold,
        "layer_2_allocation_method": layer2_allocation_method,
        "layer_2_allocation_method_canonical": layer2_allocation_method_canonical,
        "layer_2_legacy_allocation_method": layer2_legacy_allocation_method,
        "layer_2_decision_gate": layer2_decision_gate,
        "layer_2_decision_gate_canonical": layer2_decision_gate_canonical,
        "layer_2_legacy_decision_gate": layer2_legacy_decision_gate,
        "layer_2_legacy_alias_deprecation_plan": layer2_legacy_alias_deprecation_plan,
        "layer_2_near_tie_objective_gap_threshold": layer2_near_tie_objective_gap_threshold,
        "layer_2_near_tie_profit_gap_threshold": layer2_near_tie_profit_gap_threshold,
        "layer_2_objective_parameters": layer2_objective_parameters,
        "margin_proxy": {
            "main": main_margin_proxy,
            "assorti": assorti_margin_proxy,
        },
        "unit_capital_proxy": unit_capital_proxy,
        "economic_inputs": economic_inputs,
        "economic_source": economic_source,
        "layer_3_purchase_factors": layer3_purchase_factors,
        "layer_3_calibration": {
            "method": layer3_calibration_method,
            "stockout_boost_max": layer3_stockout_boost_max,
            "overstock_dampen_max": layer3_overstock_dampen_max,
            "stockout_weight_by_decision": layer3_stockout_weight_by_decision,
            "overstock_weight_by_decision": layer3_overstock_weight_by_decision,
            "factor_bounds": {
                decision: {
                    "min": bounds[0],
                    "max": bounds[1],
                }
                for decision, bounds in layer3_factor_bounds.items()
            },
        },
        "layer_proxy_source": layer_proxy_source,
        "layer5_threshold_order_adjusted": layer5_threshold_order_adjusted,
        "layer_4_scenario_factors": layer4_scenario_factors,
        "layer_4_contract_version": layer4_contract_version,
        "layer_5_unavoidable_stockout_risk_threshold": layer5_unavoidable_stockout_risk_threshold,
        "layer_5_signal_thresholds": {
            "accelerate_production": layer5_accelerate_production_risk_threshold,
            "increase_price_to_slow_velocity": layer5_unavoidable_stockout_risk_threshold,
            "reduce_order_size": layer5_reduce_order_marginal_profit_rate,
        },
        "layer_5_cost_policy_parameters": {
            "accelerate_action_cost_rate": layer5_accelerate_action_cost_rate,
            "price_slowdown_lost_volume_rate": layer5_price_slowdown_lost_volume_rate,
            "reduce_order_marginal_profit_rate": layer5_reduce_order_marginal_profit_rate,
        },
    }


def _build_explanation_steps(
    *,
    total_daily_sales: float,
    planning_horizon_days: int,
    expected_horizon_sales: float,
    ready_bundle_stock_total: int,
    competition_raw_bundle_stock: int,
    competition_raw_breakdown: str,
    physical_scope: object,
    resource_allocation: object,
    arrival_projection: object,
    shared_color_pool: dict[str, object],
    required_bundle_units: int,
    available_bundles_for_cover: int,
    bundle_deficit_total: int,
    lead_time_days_total: int,
    safety_stock_days: int,
    reorder_point_days: int,
    allow_order_with_buffer: bool,
    economic_buffer_days: int,
    target_bundle_horizon_days: int,
    size_weights_source: str,
    in_flight_source: str,
    bundle_stock_source: str,
    economics_trust: dict[str, object],
    explanation_warnings: list[dict[str, object]],
    assorti_classification_source: str,
    admin_assorti_bundle_type_ids: list[int],
    global_assorti_bundle_type_ids: list[int],
    assorti_bundle_type_count: int,
    main_bundle_type_count: int,
    assorti_classification_source_breakdown: dict[str, int],
    layer1_sku_count: int,
    layer1_avg_coverage_days: float,
    layer1_high_stockout_risk_count: int,
    layer1_high_stockout_risk_threshold: float,
    layer1_contract_status: str,
    layer2_allocation_method_canonical: str,
    layer2_allocation_method_legacy: str,
    layer2_decision_gate_canonical: str,
    layer2_decision_gate_legacy: str,
    layer2_allocation_summary: dict[str, object],
    layer2_decision_quality: dict[str, object],
    layer2_contract_status: str,
    layer3_purchase_shaping: dict[str, object],
    layer3_contract_status: str,
    layer4_scenarios: list[dict[str, object]],
    layer4_contract: dict[str, object],
    layer4_aggregate_deltas: dict[str, object],
    capital_gap_summary: dict[str, object],
    capital_constraint_summary: dict[str, object],
    capital_constraint_contract_status: str,
    layer5_intervention: dict[str, object],
    layer5_contract_status: str,
    elastic_scope_mode: str,
    applicable_elastic_type_ids: list[int],
    scoped_elastic_rows_count: int,
    elastic_scope_line_count: int,
    elastic_uplift_delta: int,
    elastic_uplift_scope: str,
    elastic_uplift_keys: list[tuple[int, int]],
    elastic_uplift_line_alloc: dict[tuple[int, int], int],
    in_flight_raw_qty_total: int,
    in_flight_effective_qty_total: int,
    in_flight_effective_lines: int,
    fabric_constraint_count: int,
    elastic_constraint_count: int,
) -> list[str]:
    return [
        (
            f"Спрос по наборам: total_daily_sales={total_daily_sales:.3f}, "
            f"planning_horizon_days={planning_horizon_days}, "
            f"expected_horizon_sales={expected_horizon_sales:.1f}."
        ),
        (
            f"Учтены ready stock наборов (WB+локальный)={ready_bundle_stock_total} и "
            f"оценка сырьевого потенциала={competition_raw_bundle_stock} "
            f"(competition-aware by bundle: {competition_raw_breakdown})."
        ),
        (
            "Physical scope: "
            f"local_stock_scope={getattr(physical_scope, 'local_stock_scope')}, "
            f"wb_stock_scope={getattr(physical_scope, 'wb_stock_scope')}, "
            f"ready_bundle_source={getattr(physical_scope, 'ready_bundle_source')}, "
            f"raw_single_source={getattr(physical_scope, 'raw_single_source')}, "
            "nsc_assembled_bundle_inventory_state="
            f"{getattr(physical_scope, 'nsc_assembled_bundle_inventory_state')}."
        ),
        (
            f"Resource allocation: mode={getattr(resource_allocation, 'mode')}, "
            f"resource_keys={getattr(resource_allocation, 'total_resource_keys')}, "
            f"competing={getattr(resource_allocation, 'competing_resource_keys')}, "
            f"reserved_units={getattr(resource_allocation, 'total_reserved_units')}, "
            f"contract_status={getattr(resource_allocation, 'contract').get('status')}."
        ),
        (
            "Arrival projection: "
            f"status={getattr(arrival_projection, 'status')}, "
            f"arrival_horizon_days={getattr(arrival_projection, 'arrival_horizon_days')}, "
            f"demand_units_until_arrival={getattr(arrival_projection, 'demand_units_until_arrival')}, "
            f"projected_supply_units_before_arrival={getattr(arrival_projection, 'projected_supply_units_before_arrival')}, "
            "projected_shortage_before_arrival="
            f"{getattr(arrival_projection, 'projected_shortage_before_arrival')}."
        ),
        (
            "Shared color pool: "
            f"status={shared_color_pool.get('status')}, "
            f"source={shared_color_pool.get('source')}, "
            f"sibling_article_count={shared_color_pool.get('sibling_article_count')}, "
            f"sibling_proxy_required_total={shared_color_pool.get('sibling_proxy_required_total')}, "
            f"observation_window_days={shared_color_pool.get('observation_window_days')}, "
            f"as_of_date={shared_color_pool.get('as_of_date')}."
        ),
        (
            f"Дефицит по модели B: target_bundle_units={required_bundle_units}, "
            f"available_for_cover={available_bundles_for_cover}, deficit={bundle_deficit_total}."
        ),
        (
            f"Reorder policy: lead_time_days={lead_time_days_total}, "
            f"safety_stock_days={safety_stock_days}, reorder_point_days={reorder_point_days}."
        ),
        (
            f"Economic buffer policy: enabled={allow_order_with_buffer}, "
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
            f"warnings={explanation_warnings}."
        ),
        (
            "Assorti classification: "
            f"source={assorti_classification_source}, "
            f"fallback_admin_ids={sorted(admin_assorti_bundle_type_ids)}, "
            f"fallback_global_ids={sorted(global_assorti_bundle_type_ids)}, "
            f"assorti_bundle_types={assorti_bundle_type_count}, "
            f"main_bundle_types={main_bundle_type_count}, "
            f"source_breakdown={assorti_classification_source_breakdown}."
        ),
        (
            f"Layer 1 stock health: sku_count={layer1_sku_count}, "
            f"avg_coverage_days={layer1_avg_coverage_days}, "
            f"high_stockout_risk_skus={layer1_high_stockout_risk_count}, "
            f"high_stockout_threshold={layer1_high_stockout_risk_threshold}, "
            f"contract_status={layer1_contract_status}."
        ),
        (
            f"Layer 2 allocation: method={layer2_allocation_method_canonical}, "
            f"legacy_method={layer2_allocation_method_legacy}, "
            f"decision_gate={layer2_decision_gate_canonical}, "
            f"legacy_decision_gate={layer2_decision_gate_legacy}, "
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
            f"contract_status={layer2_contract_status}."
        ),
        (
            "Layer 3 purchase shaping: method=allocation_decision_factors, "
            f"qty_before={layer3_purchase_shaping['qty_before']}, "
            f"qty_after_base={layer3_purchase_shaping['qty_after_base']}, "
            f"qty_after={layer3_purchase_shaping['qty_after']}, "
            f"adjusted_lines={layer3_purchase_shaping['adjusted_lines']}, "
            f"calibration_delta_vs_base={layer3_purchase_shaping['qty_delta_vs_base']}, "
            f"contract_status={layer3_contract_status}, "
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
            f"contract_status={capital_constraint_contract_status}."
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
            f"contract_status={layer5_contract_status}."
        ),
        (
            f"Elastic scope: mode={elastic_scope_mode}, "
            f"applicable_types={sorted(applicable_elastic_type_ids)}, "
            f"scoped_settings={scoped_elastic_rows_count}, "
            f"scoped_lines={elastic_scope_line_count}."
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
            f"Применены ограничения: fabric_constraints={fabric_constraint_count}, "
            f"elastic_constraints={elastic_constraint_count}."
        ),
    ]


def _build_explanation_meta(
    *,
    explanation_warnings: list[dict[str, object]],
    economics_trust: dict[str, object],
    capital_governance: dict[str, object],
    size_weights_source: str,
    in_flight_source: str,
    bundle_stock_source: str,
    physical_scope: object,
    arrival_projection: object,
    shared_color_pool: dict[str, object],
    lead_time_days_total: int,
    safety_stock_days: int,
    reorder_point_days: int,
    layer1_stock_health_metrics: list[dict[str, object]],
    layer1_avg_coverage_days: float,
    layer1_high_stockout_risk_count: int,
    layer1_high_stockout_risk_threshold: float,
    layer1_contract: dict[str, object],
    assorti_classification_source: str,
    assorti_classification_admin_fallback_source: str,
    assorti_classification_global_fallback_source: str,
    admin_assorti_bundle_type_ids: list[int],
    global_assorti_bundle_type_ids: list[int],
    assorti_bundle_type_count: int,
    main_bundle_type_count: int,
    assorti_classification_source_breakdown: dict[str, int],
    assorti_classification_by_bundle_type: dict[str, object],
    main_margin_proxy: float,
    assorti_margin_proxy: float,
    unit_capital_proxy: float,
    layer2_allocation_method: str,
    layer2_allocation_method_canonical: str,
    layer2_legacy_allocation_method: str,
    layer2_legacy_alias_deprecation_plan: dict[str, object],
    layer2_allocation_decisions: list[dict[str, object]],
    layer2_allocation_summary: dict[str, object],
    layer2_contract: dict[str, object],
    layer2_decision_quality: dict[str, object],
    layer2_decision_gate: str,
    layer2_decision_gate_canonical: str,
    layer2_legacy_decision_gate: str,
    layer2_objective_parameters: dict[str, object],
    layer2_objective_source: dict[str, object],
    layer3_purchase_factors: dict[str, object],
    layer3_contract: dict[str, object],
    layer3_purchase_shaping: dict[str, object],
    layer4_scenario_factor_items: list[dict[str, object]],
    layer4_contract: dict[str, object],
    layer4_aggregate_deltas: dict[str, object],
    layer4_scenarios: list[dict[str, object]],
    layer5_intervention_meta: dict[str, object],
    capital_gap_summary: dict[str, object],
    capital_constraint_summary: dict[str, object],
    resource_allocation: object,
    alpha_proxy_economics: dict[str, object],
    economic_buffer_enabled: bool,
    economic_buffer_days: int,
    target_bundle_horizon_days: int,
    in_flight_raw_qty_total: int,
    in_flight_effective_qty_total: int,
    in_flight_effective_lines: int,
    elastic_scope_mode: str,
    applicable_elastic_type_ids: list[int],
    scoped_elastic_rows_count: int,
    elastic_scope_line_count: int,
    elastic_uplift_delta: int,
    elastic_uplift_scope: str,
    elastic_uplift_keys: list[tuple[int, int]],
    elastic_uplift_line_alloc: dict[tuple[int, int], int],
) -> dict[str, object]:
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

    return {
        "warnings": explanation_warnings,
        "economics_trust": economics_trust,
        "capital_governance": capital_governance,
        "sources": {
            "size_weights": size_weights_source,
            "in_flight": in_flight_source,
            "bundle_stock": bundle_stock_source,
        },
        "physical_scope": physical_scope.model_dump(mode="python"),
        "arrival_projection": arrival_projection.model_dump(mode="python"),
        "shared_color_pool": shared_color_pool,
        "reorder_policy": {
            "lead_time_days_total": lead_time_days_total,
            "safety_stock_days": safety_stock_days,
            "reorder_point_days": reorder_point_days,
        },
        "layer_1_stock_health": {
            "metrics": layer1_stock_health_metrics,
            "summary": {
                "sku_count": len(layer1_stock_health_metrics),
                "avg_coverage_days": layer1_avg_coverage_days,
                "high_stockout_risk_skus": layer1_high_stockout_risk_count,
                "high_stockout_risk_threshold": layer1_high_stockout_risk_threshold,
            },
            "contract": layer1_contract,
            "assorti_classification": {
                "source": assorti_classification_source,
                "fallback_sources": [
                    assorti_classification_admin_fallback_source,
                    assorti_classification_global_fallback_source,
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
                "main_margin": main_margin_proxy,
                "assorti_margin": assorti_margin_proxy,
                "unit_capital": unit_capital_proxy,
            },
        },
        "layer_2_allocation": {
            "method": layer2_allocation_method,
            "method_canonical": layer2_allocation_method_canonical,
            "legacy_method": layer2_legacy_allocation_method,
            "legacy_alias_deprecation_plan": layer2_legacy_alias_deprecation_plan,
            "decisions": layer2_allocation_decisions,
            "summary": layer2_allocation_summary,
            "contract": layer2_contract,
            "decision_quality": layer2_decision_quality,
            "decision_gate": layer2_decision_gate,
            "decision_gate_canonical": layer2_decision_gate_canonical,
            "legacy_decision_gate": layer2_legacy_decision_gate,
            "tie_break": "hold",
            "gmroi_usage": "diagnostic_only",
            "objective_formula": (
                "expected_gross_profit_until_eta"
                "-capital_cost_penalty"
                "-stockout_penalty"
                "-overstock_penalty"
            ),
            "objective_parameters": layer2_objective_parameters,
            "objective_source": layer2_objective_source,
        },
        "layer_3_purchase_shaping": {
            "method": "allocation_decision_factors",
            "factors": layer3_purchase_factors,
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
        "resource_allocation": resource_allocation.model_dump(mode="python"),
        "alpha_proxy_economics": alpha_proxy_economics,
        "economic_buffer": {
            "enabled": economic_buffer_enabled,
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
            "scoped_settings": scoped_elastic_rows_count,
            "scoped_lines": elastic_scope_line_count,
        },
        "elastic_uplift": {
            "delta": elastic_uplift_delta,
            "scope": elastic_uplift_scope,
            "affected_lines": len(elastic_uplift_keys),
            "line_keys": elastic_uplift_line_keys_items,
            "line_alloc": elastic_uplift_line_alloc_items,
        },
    }


def _build_from_wb_explainability_inputs(
    *,
    requested_as_of_date: date | None,
    effective_as_of_date: date | None,
    observation_window_days: int,
    bundle_type_ids: list[int],
    daily_sales_by_bundle: dict[int, float],
    wb_stock_by_bundle: dict[int, int],
    freshness_sales_age_days: int | None,
    freshness_stock_oldest_age_days: int | None,
) -> dict[str, object]:
    requested_as_of_date_value = (
        requested_as_of_date.isoformat() if requested_as_of_date is not None else None
    )
    as_of_date_value = effective_as_of_date.isoformat() if effective_as_of_date is not None else None
    requested_as_of_text = requested_as_of_date_value or "none"
    as_of_text = as_of_date_value or "none"

    if effective_as_of_date is None:
        as_of_source = "none"
    elif requested_as_of_date is None:
        as_of_source = "latest_sales"
    elif requested_as_of_date != effective_as_of_date:
        as_of_source = "clamped_to_latest_sales"
    else:
        as_of_source = "request"

    if effective_as_of_date is not None:
        window_start_date = (
            effective_as_of_date - timedelta(days=observation_window_days - 1)
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
        "none"
        if freshness_stock_oldest_age_days is None
        else str(freshness_stock_oldest_age_days)
    )

    return {
        "requested_as_of_date": requested_as_of_date_value,
        "as_of_date": as_of_date_value,
        "as_of_source": as_of_source,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "window_text": window_text,
        "daily_sales_snapshot": daily_sales_snapshot,
        "wb_stock_snapshot": wb_stock_snapshot,
        "requested_as_of_text": requested_as_of_text,
        "as_of_text": as_of_text,
        "freshness_sales_age_days_text": freshness_sales_age_days_text,
        "freshness_stock_oldest_age_days_text": freshness_stock_oldest_age_days_text,
    }


def _apply_from_wb_explainability(
    *,
    explanation: ProductionOrderExplanationBlock,
    observation_window_days: int,
    freshness_mode: str,
    requested_as_of_date: str | None,
    as_of_date: str | None,
    as_of_source: str,
    bundle_type_ids: list[int],
    window_start_date: str | None,
    window_end_date: str | None,
    window_text: str,
    daily_sales_snapshot: dict[int, float],
    wb_stock_snapshot: dict[int, int],
    wb_stock_updated_at_by_bundle: dict[int, object],
    observed_price_calibration: dict[str, object],
    observed_commission_calibration: dict[str, object],
    freshness_status: str,
    freshness_sales_age_days: int | None,
    freshness_stock_oldest_age_days: int | None,
    freshness_stock_age_days_by_bundle: dict[int, int | None],
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    freshness_threshold_source: dict[str, object],
    requested_as_of_text: str,
    as_of_text: str,
    freshness_sales_age_days_text: str,
    freshness_stock_oldest_age_days_text: str,
) -> ProductionOrderExplanationBlock:
    explanation.meta["from_wb"] = {
        "observation_window_days": observation_window_days,
        "freshness_mode": freshness_mode,
        "requested_as_of_date": requested_as_of_date,
        "as_of_date": as_of_date,
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

    explanation.steps.insert(
        0,
        (
            "WB ingestion adapter: "
            f"observation_window_days={observation_window_days}, "
            f"freshness_mode={freshness_mode}, "
            f"requested_as_of_date={requested_as_of_text}, "
            f"as_of_date={as_of_text}, as_of_source={as_of_source}, "
            f"bundle_type_ids={bundle_type_ids}."
            f" sales_window={window_text},"
            f" daily_sales_by_bundle={daily_sales_snapshot}, "
            f"wb_stock_by_bundle={wb_stock_snapshot}, "
            f"wb_stock_updated_at_by_bundle={wb_stock_updated_at_by_bundle}, "
            f"economic_observed_prices={observed_price_calibration.get('prices')}, "
            f"economic_observed_source={observed_price_calibration.get('source')}, "
            "economic_observed_commission="
            f"{observed_commission_calibration.get('commission_percent')}, "
            "economic_observed_commission_status="
            f"{observed_commission_calibration.get('status')}, "
            "economic_observed_commission_source="
            f"{observed_commission_calibration.get('source')}, "
            f"freshness_status={freshness_status}, "
            f"freshness_sales_age_days={freshness_sales_age_days_text}, "
            "freshness_stock_oldest_age_days="
            f"{freshness_stock_oldest_age_days_text}, "
            "freshness_stock_age_days_by_bundle="
            f"{freshness_stock_age_days_by_bundle}, "
            "freshness_threshold_days="
            f"sales:{sales_stale_after_days}|stock:{stock_stale_after_days}, "
            "freshness_threshold_source="
            f"sales:{freshness_threshold_source['sales']}|stock:{freshness_threshold_source['stock']}."
        ),
    )
    return explanation


def _finalize_from_wb_explainability(
    *,
    explanation: ProductionOrderExplanationBlock,
    explainability_mode: str,
    requested_as_of_date: date | None,
    effective_as_of_date: date | None,
    observation_window_days: int,
    freshness_mode: str,
    bundle_type_ids: list[int],
    daily_sales_by_bundle: dict[int, float],
    wb_stock_by_bundle: dict[int, int],
    wb_stock_updated_at_by_bundle: dict[int, object],
    observed_price_calibration: dict[str, object],
    observed_commission_calibration: dict[str, object],
    freshness_status: str,
    freshness_sales_age_days: int | None,
    freshness_stock_oldest_age_days: int | None,
    freshness_stock_age_days_by_bundle: dict[int, int | None],
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    freshness_threshold_source: dict[str, object],
) -> ProductionOrderExplanationBlock:
    from_wb_explainability_inputs = _build_from_wb_explainability_inputs(
        requested_as_of_date=requested_as_of_date,
        effective_as_of_date=effective_as_of_date,
        observation_window_days=observation_window_days,
        bundle_type_ids=bundle_type_ids,
        daily_sales_by_bundle=daily_sales_by_bundle,
        wb_stock_by_bundle=wb_stock_by_bundle,
        freshness_sales_age_days=freshness_sales_age_days,
        freshness_stock_oldest_age_days=freshness_stock_oldest_age_days,
    )
    explanation = _apply_from_wb_explainability(
        explanation=explanation,
        observation_window_days=observation_window_days,
        freshness_mode=freshness_mode,
        bundle_type_ids=bundle_type_ids,
        wb_stock_updated_at_by_bundle=wb_stock_updated_at_by_bundle,
        observed_price_calibration=observed_price_calibration,
        observed_commission_calibration=observed_commission_calibration,
        freshness_status=freshness_status,
        freshness_sales_age_days=freshness_sales_age_days,
        freshness_stock_oldest_age_days=freshness_stock_oldest_age_days,
        freshness_stock_age_days_by_bundle=freshness_stock_age_days_by_bundle,
        sales_stale_after_days=sales_stale_after_days,
        stock_stale_after_days=stock_stale_after_days,
        freshness_threshold_source=freshness_threshold_source,
        **from_wb_explainability_inputs,
    )
    return _apply_explainability_mode(
        explanation=explanation,
        mode=explainability_mode,
    )


def _build_compact_explanation_meta(meta: dict[str, object]) -> dict[str, object]:
    compact_meta: dict[str, object] = {
        "warnings": meta.get("warnings", []),
        "economics_trust": meta.get("economics_trust", {}),
        "capital_governance": meta.get("capital_governance", {}),
        "sources": meta.get("sources", {}),
        "physical_scope": meta.get("physical_scope", {}),
        "arrival_projection": meta.get("arrival_projection", {}),
        "reorder_policy": meta.get("reorder_policy", {}),
        "economic_buffer": meta.get("economic_buffer", {}),
        "in_flight_effective": meta.get("in_flight_effective", {}),
        "capital_gap": meta.get("capital_gap", {}),
        "capital_constraint": meta.get("capital_constraint", {}),
        "resource_allocation": meta.get("resource_allocation", {}),
        "shared_color_pool": meta.get("shared_color_pool", {}),
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
                        "objective_score_delta_vs_balanced": scenario.get(
                            "objective_score_delta_vs_balanced"
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
