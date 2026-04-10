from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderRecommendationLine


@dataclass(frozen=True)
class _CapitalApplicationResult:
    candidate_lines: list[ProductionOrderRecommendationLine]
    capital_rankings: list[dict[str, int | float | str]]
    capital_constraint_summary: dict[str, object]
    capital_constraint_contract: dict[str, str | dict[str, bool]]
    candidate_total_units: int


def _apply_production_order_capital_constraints(
    *,
    candidate_lines: list[ProductionOrderRecommendationLine],
    layer3_decision_by_line: dict[tuple[int, int], str],
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    margin_main_per_unit: float,
    margin_assorti_per_unit: float,
    unit_capital_per_unit: float,
    available_capital: float | None,
    capital_cost_rate: float,
    stockout_penalty_weight: float,
    overstock_penalty_weight: float,
    build_line_objective_capital_rankings: Callable[..., list[dict[str, int | float | str]]],
    apply_capital_constraint_to_candidate_lines: Callable[..., tuple[list[ProductionOrderRecommendationLine], dict[str, object]]],
    build_capital_constraint_contract_summary: Callable[..., dict[str, str | dict[str, bool]]],
) -> _CapitalApplicationResult:
    capital_rankings = build_line_objective_capital_rankings(
        candidate_lines=candidate_lines,
        layer3_decision_by_line=layer3_decision_by_line,
        layer1_stock_health_metrics=layer1_stock_health_metrics,
        margin_main_per_unit=margin_main_per_unit,
        margin_assorti_per_unit=margin_assorti_per_unit,
        unit_capital_per_unit=unit_capital_per_unit,
        capital_cost_rate=capital_cost_rate,
        stockout_penalty_weight=stockout_penalty_weight,
        overstock_penalty_weight=overstock_penalty_weight,
    )
    candidate_lines, capital_constraint_summary = apply_capital_constraint_to_candidate_lines(
        candidate_lines=candidate_lines,
        ranked_line_objectives=capital_rankings,
        available_capital=available_capital,
        unit_capital_per_unit=unit_capital_per_unit,
    )
    capital_constraint_contract = build_capital_constraint_contract_summary(
        capital_constraint_summary,
    )
    capital_constraint_summary = {
        **capital_constraint_summary,
        "contract": capital_constraint_contract,
    }
    candidate_total_units = sum(line.recommended_qty for line in candidate_lines)

    return _CapitalApplicationResult(
        candidate_lines=candidate_lines,
        capital_rankings=capital_rankings,
        capital_constraint_summary=capital_constraint_summary,
        capital_constraint_contract=capital_constraint_contract,
        candidate_total_units=candidate_total_units,
    )
