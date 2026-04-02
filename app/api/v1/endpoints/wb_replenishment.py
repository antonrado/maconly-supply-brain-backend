from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import (
    WbReplenishmentRequest,
    WbReplenishmentResponse,
)
from app.services.wb_replenishment import compute_replenishment


def _build_invalid_wb_arrival_date_detail(*, target_date: object, wb_arrival_date: object) -> dict[str, object]:
    return {
        "code": "wb_arrival_date_before_target_date",
        "message": "wb_arrival_date cannot be earlier than target_date",
        "field": "wb_arrival_date",
        "field_metadata": {
            "description": "Requested WB arrival date",
            "type": "date",
        },
        "target_date": str(target_date),
        "wb_arrival_date": str(wb_arrival_date),
        "next_steps": ["use_wb_arrival_date_on_or_after_target_date"],
    }


router = APIRouter()


@router.post("/proposal", response_model=WbReplenishmentResponse)
def wb_replenishment_proposal(
    payload: WbReplenishmentRequest,
    db: Session = Depends(get_db),
) -> WbReplenishmentResponse:
    if payload.wb_arrival_date < payload.target_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_build_invalid_wb_arrival_date_detail(
                target_date=payload.target_date,
                wb_arrival_date=payload.wb_arrival_date,
            ),
        )

    items = compute_replenishment(db=db, payload=payload)
    return WbReplenishmentResponse(
        target_date=payload.target_date,
        wb_arrival_date=payload.wb_arrival_date,
        items=items,
    )
