from __future__ import annotations

from dataclasses import dataclass

from app.schemas.planning_production_order import ProductionOrderProposalResponse
from app.services.planning_production_order_response_application import (
    _ResponseApplicationResult,
)


@dataclass(frozen=True)
class _ResponseUnpackApplicationResult:
    response: ProductionOrderProposalResponse


def _apply_production_order_response_unpack(
    *,
    response_application: _ResponseApplicationResult,
) -> _ResponseUnpackApplicationResult:
    return _ResponseUnpackApplicationResult(
        response=response_application.response,
    )
