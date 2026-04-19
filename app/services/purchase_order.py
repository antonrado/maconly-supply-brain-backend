from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import PurchaseOrder, PurchaseOrderItem
from app.schemas.order_proposal import OrderProposalResponse
from app.schemas.planning_production_order import ProductionOrderProposalFromWbRequest
from app.services.order_proposal import generate_order_proposal
from app.services.planning_production_order import build_production_order_proposal_from_wb


def _map_target_date_to_planning_horizon_days(target_date: date) -> int:
    planning_horizon_days = (target_date - date.today()).days
    if planning_horizon_days < 1:
        return 1
    if planning_horizon_days > 365:
        return 365
    return planning_horizon_days


def create_purchase_order_from_proposal(
    db: Session,
    target_date: date,
    article_id: int | None = None,
    explanation: bool = True,
    comment: str | None = None,
) -> PurchaseOrder:
    """Create a draft PurchaseOrder based on current order proposal for a target_date.

    All proposal items are converted into PurchaseOrderItem rows with source="auto".
    """
    proposal_items: list[tuple[int, int, int, int]] = []
    if article_id is not None:
        canonical_request = ProductionOrderProposalFromWbRequest(
            article_id=article_id,
            planning_horizon_days=_map_target_date_to_planning_horizon_days(target_date),
            explainability_mode="full" if explanation else "compact",
        )
        canonical_proposal = build_production_order_proposal_from_wb(
            db=db,
            request=canonical_request,
        )
        recommendation = canonical_proposal.recommendation
        if recommendation is not None:
            proposal_items = [
                (
                    line.article_id,
                    line.color_id,
                    line.size_id,
                    line.recommended_qty,
                )
                for line in recommendation.lines
                if line.recommended_qty > 0
            ]
    else:
        proposal: OrderProposalResponse = generate_order_proposal(
            db=db,
            target_date=target_date,
            explanation=explanation,
        )
        proposal_items = [
            (
                item.article_id,
                item.color_id,
                item.size_id,
                item.quantity,
            )
            for item in proposal.items
            if item.quantity > 0
        ]

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

    for line_article_id, color_id, size_id, quantity in proposal_items:
        poi = PurchaseOrderItem(
            purchase_order_id=po.id,
            article_id=line_article_id,
            color_id=color_id,
            size_id=size_id,
            quantity=quantity,
            source="auto",
            notes=None,
        )
        db.add(poi)

    db.commit()
    db.refresh(po)
    return po
