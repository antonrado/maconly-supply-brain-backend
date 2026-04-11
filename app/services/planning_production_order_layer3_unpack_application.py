from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer3_application import (
    _Layer3ApplicationResult,
)


@dataclass(frozen=True)
class _Layer3UnpackApplicationResult:
    layer3_decision_by_line: dict[tuple[int, int], str]
    layer3_purchase_shaping: dict[str, int | float | dict[str, object] | str]
    layer3_contract: dict[str, object]


def _apply_production_order_layer3_unpack(
    *,
    layer3_application: _Layer3ApplicationResult,
) -> _Layer3UnpackApplicationResult:
    return _Layer3UnpackApplicationResult(
        layer3_decision_by_line=layer3_application.layer3_decision_by_line,
        layer3_purchase_shaping=layer3_application.layer3_purchase_shaping,
        layer3_contract=layer3_application.layer3_contract,
    )
