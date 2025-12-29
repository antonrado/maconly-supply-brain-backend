from __future__ import annotations

from fastapi import APIRouter, HTTPException, status


router = APIRouter()


@router.get("/core/health")
async def get_planning_core_health() -> None:
    """Skeleton endpoint for Planning Core health.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 501 to make it explicit that Planning Core v1 has no behaviour yet.
    """

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not Implemented",
    )


@router.post("/core/proposal")
async def create_planning_core_proposal() -> None:
    """Skeleton endpoint for computing an order proposal.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 501 to make it explicit that Planning Core v1 has no behaviour yet.
    """

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not Implemented",
    )
