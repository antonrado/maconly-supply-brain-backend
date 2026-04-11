from __future__ import annotations

from collections import defaultdict

from app.services.planning_production_order_capital import (
    _bounded_unit_float,
    _compute_objective_components,
)
from app.services.planning_production_order_layer_proxy import (
    LAYER2_CAPITAL_COST_RATE,
    LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    LAYER2_STOCKOUT_PENALTY_WEIGHT,
)

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
LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD = 1.0
LAYER2_NEAR_TIE_PROFIT_GAP_THRESHOLD = LAYER2_NEAR_TIE_OBJECTIVE_GAP_THRESHOLD
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
    for size_id in size_ids:
        normalized.setdefault(size_id, 0.0)

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    return {size_id: normalized[size_id] / norm_total for size_id in size_ids}


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
        stockout_risk = _bounded_unit_float(current_stock_by_color_size.get("stockout_risk", 0.0))
        overstock_risk = _bounded_unit_float(current_stock_by_color_size.get("overstock_risk", 0.0))

        available_units = current_stock + in_flight_effective
        if velocity_main + velocity_assorti <= 0:
            coverage_days = 9999.0
            stockout_risk = 0.0
        else:
            coverage_days = float(available_units) / (velocity_main + velocity_assorti)
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

        if velocity_main + velocity_assorti > 0:
            gross_margin = (
                (velocity_main * margin_main)
                + (velocity_assorti * margin_assorti)
            ) / (velocity_main + velocity_assorti)
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
            continue

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
