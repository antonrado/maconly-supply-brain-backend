from __future__ import annotations

from datetime import datetime, timedelta

from app.schemas.planning_production_order import (
    ProductionOrderAlternative,
    ProductionOrderArrivalProjection,
    ProductionOrderRecommendation,
    ProductionOrderRecommendationLine,
)


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


def build_recommendation_and_alternatives(
    *,
    arrival_projection: ProductionOrderArrivalProjection,
    total_daily_sales: float,
    risk_level: str,
    candidate_total_units: int,
    allow_order_with_buffer: bool,
    priority: int,
    lead_time_days_total: int,
    now: datetime,
    candidate_lines: list[ProductionOrderRecommendationLine],
) -> tuple[str, ProductionOrderRecommendation, list[ProductionOrderAlternative]]:
    if arrival_projection.status == "safe_cover_until_arrival" and total_daily_sales > 0:
        action = "wait"
    else:
        action_risk_level = risk_level
        if (
            arrival_projection.status == "shortage_before_arrival"
            and risk_level not in {"critical", "warning"}
        ):
            action_risk_level = "critical"
        action = _choose_action(
            risk_level=action_risk_level,
            candidate_units=candidate_total_units,
            allow_order_with_buffer=allow_order_with_buffer,
        )

    target_arrival_date = (now + timedelta(days=lead_time_days_total)).date()
    if action == "wait":
        recommendation = ProductionOrderRecommendation(
            action="wait",
            priority=priority,
            target_arrival_date=target_arrival_date,
            total_units=0,
            lines=[],
        )
    else:
        recommendation = ProductionOrderRecommendation(
            action=action,
            priority=priority,
            target_arrival_date=target_arrival_date,
            total_units=candidate_total_units,
            lines=candidate_lines,
        )

    alternatives = _build_alternatives(action)
    return action, recommendation, alternatives
