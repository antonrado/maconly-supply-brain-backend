from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer5ApplicationResult:
    layer5_intervention: dict[str, object]
    layer5_contract: dict[str, str | int | dict[str, bool]]
    layer5_intervention_meta: dict[str, object]


def _apply_production_order_layer5_analysis(
    *,
    risk_level: str,
    layer4_scenarios: list[dict[str, str | int | float]],
    in_flight_effective_qty_total: int,
    unavoidable_stockout_risk_threshold: float,
    accelerate_production_risk_threshold: float,
    accelerate_action_cost_rate: float,
    price_slowdown_lost_volume_rate: float,
    reduce_order_marginal_profit_rate: float,
    build_layer5_intervention_signals: Callable[..., dict[str, object]],
    build_layer5_contract_summary: Callable[..., dict[str, str | int | dict[str, bool]]],
) -> _Layer5ApplicationResult:
    layer5_intervention = build_layer5_intervention_signals(
        risk_level=risk_level,
        layer4_scenarios=layer4_scenarios,
        in_flight_effective_qty_total=in_flight_effective_qty_total,
        unavoidable_stockout_risk_threshold=unavoidable_stockout_risk_threshold,
        accelerate_production_risk_threshold=accelerate_production_risk_threshold,
        accelerate_action_cost_rate=accelerate_action_cost_rate,
        price_slowdown_lost_volume_rate=price_slowdown_lost_volume_rate,
        reduce_order_marginal_profit_rate=reduce_order_marginal_profit_rate,
    )
    layer5_contract = build_layer5_contract_summary(
        layer5_intervention=layer5_intervention,
        layer4_scenarios=layer4_scenarios,
        unavoidable_stockout_risk_threshold=unavoidable_stockout_risk_threshold,
        accelerate_production_risk_threshold=accelerate_production_risk_threshold,
        reduce_order_marginal_profit_rate=reduce_order_marginal_profit_rate,
    )
    layer5_intervention_meta = {
        **layer5_intervention,
        "contract": layer5_contract,
    }

    return _Layer5ApplicationResult(
        layer5_intervention=layer5_intervention,
        layer5_contract=layer5_contract,
        layer5_intervention_meta=layer5_intervention_meta,
    )
