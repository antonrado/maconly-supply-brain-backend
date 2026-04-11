from __future__ import annotations

from app.schemas.planning_production_order import ProductionOrderRecommendationLine
from app.services.planning_production_order_economics import (
    ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_ASSORTI,
    ECONOMICS_DEFAULT_AVERAGE_REALIZED_PRICE_MAIN,
)
from app.services.planning_production_order_layer_proxy import (
    LAYER2_CAPITAL_COST_RATE,
    LAYER2_OVERSTOCK_PENALTY_WEIGHT,
    LAYER2_STOCKOUT_PENALTY_WEIGHT,
)

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


def _bounded_unit_float(value: object) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(min(normalized, 1.0), 0.0)


def _ceil_to_int(value: float) -> int:
    as_int = int(value)
    if value > as_int:
        return as_int + 1
    return as_int


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
