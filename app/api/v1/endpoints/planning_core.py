from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/core/health")
async def get_planning_core_health() -> dict:
    """Skeleton endpoint for Planning Core health.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 200 with a static stub payload; no planning logic is executed.
    """

    return {"status": "ok"}


@router.post("/core/proposal")
async def create_planning_core_proposal() -> dict:
    """Skeleton endpoint for computing an order proposal.

    For now this endpoint is intentionally not implemented and always returns
    HTTP 200 with a static stub payload; no planning logic is executed.
    """

    return {"status": "ok", "proposal": None}
