from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.order_proposal import OrderProposalResponse
from app.services.order_proposal import generate_order_proposal


router = APIRouter()

LEGACY_ORDER_PROPOSAL_DEPRECATION = "true"
LEGACY_ORDER_PROPOSAL_SUCCESSOR = "/api/v1/planning/core/production-order/proposal"
LEGACY_ORDER_PROPOSAL_FIDELITY = "legacy_live_low_fidelity"
LEGACY_ORDER_PROPOSAL_PHASE = "deprecated_runtime_supported"


@router.get(
    "/order-proposal",
    response_model=OrderProposalResponse,
    deprecated=True,
    summary="Legacy low-fidelity order proposal",
    include_in_schema=False,
)
def get_order_proposal(
    target_date: date,
    response: Response,
    explanation: bool = True,
    db: Session = Depends(get_db),
):
    response.headers["Deprecation"] = LEGACY_ORDER_PROPOSAL_DEPRECATION
    response.headers["X-Planning-Fidelity"] = LEGACY_ORDER_PROPOSAL_FIDELITY
    response.headers["X-Planning-Successor"] = LEGACY_ORDER_PROPOSAL_SUCCESSOR
    response.headers["X-Planning-Legacy-Phase"] = LEGACY_ORDER_PROPOSAL_PHASE
    return generate_order_proposal(
        db=db,
        target_date=target_date,
        explanation=explanation,
    )
