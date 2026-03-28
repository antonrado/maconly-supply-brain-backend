from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.planning.domain import PlanningProposalRequest
from app.core.planning.service import PlanningService
from app.schemas.planning_production_order import (
    ProductionOrderProposalFromWbRequest,
    ProductionOrderProposalRequest,
    ProductionOrderProposalResponse,
)
from app.schemas.planning_production_order_admin import (
    ProductionOrderAdminSettingsResponse,
    ProductionOrderAdminSettingsUpsertRequest,
)
from app.services.planning_production_order_admin import (
    get_production_order_admin_settings,
    upsert_production_order_admin_settings,
)
from app.services.planning_production_order import (
    build_production_order_proposal,
    build_production_order_proposal_from_wb,
)


router = APIRouter()

LEGACY_CORE_PROPOSAL_DEPRECATION = "true"
LEGACY_CORE_PROPOSAL_SUCCESSOR = "/api/v1/planning/core/production-order/proposal"
LEGACY_CORE_PROPOSAL_FIDELITY = "stub_legacy_low_fidelity"
LEGACY_CORE_PROPOSAL_PHASE = "deprecated_runtime_supported"


@router.get("/core/health")
async def get_planning_core_health() -> dict:
    """Skeleton endpoint for Planning Core health.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 200 with a static stub payload; no planning logic is executed.
    """

    return {"status": "ok"}


@router.post(
    "/core/proposal",
    deprecated=True,
    summary="Legacy low-fidelity core proposal stub",
    include_in_schema=False,
)
async def create_planning_core_proposal(
    request: PlanningProposalRequest,
    response: Response,
) -> dict:
    """Skeleton endpoint for computing an order proposal.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 200 with a static stub payload; no planning logic is executed.
    """

    response.headers["Deprecation"] = LEGACY_CORE_PROPOSAL_DEPRECATION
    response.headers["X-Planning-Fidelity"] = LEGACY_CORE_PROPOSAL_FIDELITY
    response.headers["X-Planning-Successor"] = LEGACY_CORE_PROPOSAL_SUCCESSOR
    response.headers["X-Planning-Legacy-Phase"] = LEGACY_CORE_PROPOSAL_PHASE

    service = PlanningService()
    proposal = service.build_proposal(request.sales_window_days, request.horizon_days)

    return {
        "status": "ok",
        "proposal": proposal.dict(),
    }


@router.post(
    "/core/production-order/proposal",
    response_model=ProductionOrderProposalResponse,
)
async def create_production_order_proposal(
    request: ProductionOrderProposalRequest,
    db: Session = Depends(get_db),
) -> ProductionOrderProposalResponse:
    return build_production_order_proposal(db=db, request=request)


@router.post(
    "/core/production-order/proposal/from-wb",
    response_model=ProductionOrderProposalResponse,
)
async def create_production_order_proposal_from_wb(
    request: ProductionOrderProposalFromWbRequest,
    db: Session = Depends(get_db),
) -> ProductionOrderProposalResponse:
    return build_production_order_proposal_from_wb(db=db, request=request)


@router.get(
    "/core/production-order/settings/{article_id}",
    response_model=ProductionOrderAdminSettingsResponse,
)
async def read_production_order_admin_settings(
    article_id: int,
    db: Session = Depends(get_db),
) -> ProductionOrderAdminSettingsResponse:
    return get_production_order_admin_settings(db=db, article_id=article_id)


@router.put(
    "/core/production-order/settings/{article_id}",
    response_model=ProductionOrderAdminSettingsResponse,
)
async def write_production_order_admin_settings(
    article_id: int,
    payload: ProductionOrderAdminSettingsUpsertRequest,
    db: Session = Depends(get_db),
) -> ProductionOrderAdminSettingsResponse:
    return upsert_production_order_admin_settings(
        db=db,
        article_id=article_id,
        payload=payload,
    )
