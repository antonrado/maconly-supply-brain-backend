from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Layer3ApplicationResult:
    layer3_decision_by_line: dict[tuple[int, int], str]
    layer3_purchase_shaping: dict[str, int | float | dict[str, object] | str]
    layer3_contract: dict[str, object]


def _apply_production_order_layer3(
    *,
    line_qty: dict[tuple[int, int], int],
    layer2_allocation_decisions: list[dict[str, int | float | str]],
    layer1_stock_health_metrics: list[dict[str, int | float | None]],
    layer3_stockout_boost_max: float,
    layer3_overstock_dampen_max: float,
    apply_layer3_purchase_shaping: Callable[
        ..., tuple[dict[tuple[int, int], str], dict[str, int | float | dict[str, object] | str]]
    ],
    build_layer3_contract_summary: Callable[[dict[str, object]], dict[str, object]],
) -> _Layer3ApplicationResult:
    layer3_decision_by_line, layer3_purchase_shaping = apply_layer3_purchase_shaping(
        line_qty=line_qty,
        layer2_allocation_decisions=layer2_allocation_decisions,
        layer1_stock_health_metrics=layer1_stock_health_metrics,
        layer3_stockout_boost_max=layer3_stockout_boost_max,
        layer3_overstock_dampen_max=layer3_overstock_dampen_max,
    )
    layer3_contract = build_layer3_contract_summary(layer3_purchase_shaping)
    return _Layer3ApplicationResult(
        layer3_decision_by_line=layer3_decision_by_line,
        layer3_purchase_shaping=layer3_purchase_shaping,
        layer3_contract=layer3_contract,
    )
