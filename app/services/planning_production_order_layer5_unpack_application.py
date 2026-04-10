from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_layer5_application import (
    _Layer5ApplicationResult,
)


@dataclass(frozen=True)
class _Layer5UnpackApplicationResult:
    layer5_intervention: dict[str, object]
    layer5_contract: dict[str, str | int | dict[str, bool]]
    layer5_intervention_meta: dict[str, object]


def _apply_production_order_layer5_unpack(
    *,
    layer5_application: _Layer5ApplicationResult,
) -> _Layer5UnpackApplicationResult:
    return _Layer5UnpackApplicationResult(
        layer5_intervention=layer5_application.layer5_intervention,
        layer5_contract=layer5_application.layer5_contract,
        layer5_intervention_meta=layer5_application.layer5_intervention_meta,
    )
