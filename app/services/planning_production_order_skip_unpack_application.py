from __future__ import annotations

from dataclasses import dataclass

from app.services.planning_production_order_skip_application import (
    _SkipApplicationResult,
)
from app.schemas.planning_production_order import ProductionOrderProposalResponse


@dataclass(frozen=True)
class _SkipUnpackApplicationResult:
    response: ProductionOrderProposalResponse


def _apply_production_order_skip_unpack(
    *,
    skip_application: _SkipApplicationResult,
) -> _SkipUnpackApplicationResult:
    return _SkipUnpackApplicationResult(response=skip_application.response)
