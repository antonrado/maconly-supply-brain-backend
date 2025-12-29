from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import PurchaseOrder, PurchaseOrderItem
from app.schemas.order_proposal import OrderProposalResponse
from app.services.order_proposal import generate_order_proposal


def create_purchase_order_from_proposal(
    db: Session,
    target_date: date,
    explanation: bool = True,
    comment: str | None = None,
) -> PurchaseOrder:
    """Create a draft PurchaseOrder based on current order proposal for a target_date.

    All proposal items are converted into PurchaseOrderItem rows with source="auto".
    """
    proposal: OrderProposalResponse = generate_order_proposal(
        db=db,
        target_date=target_date,
        explanation=explanation,
    )

    now = datetime.now(timezone.utc)
    po = PurchaseOrder(
        status="draft",
        target_date=target_date,
        comment=comment,
        external_ref=None,
        created_at=now,
        updated_at=now,
    )
    db.add(po)
    db.flush()

    for item in proposal.items:
        poi = PurchaseOrderItem(
            purchase_order_id=po.id,
            article_id=item.article_id,
            color_id=item.color_id,
            size_id=item.size_id,
            quantity=item.quantity,
            source="auto",
            notes=None,
        )
        db.add(poi)

    db.commit()
    db.refresh(po)
    return po
