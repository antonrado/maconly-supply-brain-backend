from __future__ import annotations

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import WbManagerOnlineResponse
from app.services.wb_manager import compute_manager_stats


router = APIRouter()


@router.get(
    "/online",
    response_model=WbManagerOnlineResponse,
    tags=["WB Manager Public API"],
    summary="Get WB manager online dashboard stats",
    description=(
        "Returns aggregated WB sales and stock metrics per SKU for the given "
        "target_date, optionally filtered by a list of article IDs."
    ),
)
def wb_manager_online(
    target_date: date,
    article_ids: List[int] | None = Query(
        default=None,
        description="Optional list of article IDs to filter by",
    ),
    db: Session = Depends(get_db),
) -> WbManagerOnlineResponse:
    stats = compute_manager_stats(
        db=db,
        target_date=target_date,
        article_ids=article_ids,
    )
    return WbManagerOnlineResponse(
        target_date=target_date,
        items=stats,
    )
