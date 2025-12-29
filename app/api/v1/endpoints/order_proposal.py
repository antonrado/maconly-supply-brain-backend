from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.order_proposal import OrderProposalResponse
from app.services.order_proposal import generate_order_proposal


router = APIRouter()


@router.get("/order-proposal", response_model=OrderProposalResponse)
def get_order_proposal(
    target_date: date,
    explanation: bool = True,
    db: Session = Depends(get_db),
):
    return generate_order_proposal(
        db=db,
        target_date=target_date,
        explanation=explanation,
    )
