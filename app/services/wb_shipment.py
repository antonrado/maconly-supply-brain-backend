from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import WbShipment, WbShipmentItem
from app.schemas.wb_shipment import WbShipmentCreate
from app.schemas.wb_replenishment import WbReplenishmentRequest
from app.services.wb_replenishment import compute_replenishment


def create_wb_shipment_from_proposal(
    db: Session,
    payload: WbShipmentCreate,
) -> WbShipment:
    """Create a draft WB shipment based on current WB replenishment proposal.

    The function reuses compute_replenishment logic and persists all recommendation
    fields into wb_shipment and wb_shipment_item rows. final_qty is initialized
    from recommended_qty and can be edited later while shipment is in draft status.
    """
    repl_request = WbReplenishmentRequest(
        target_date=payload.target_date,
        wb_arrival_date=payload.wb_arrival_date,
        target_coverage_days=payload.target_coverage_days,
        min_coverage_days=payload.min_coverage_days,
        replenishment_strategy=payload.replenishment_strategy,
        zero_sales_policy=payload.zero_sales_policy,
        max_coverage_days_after=payload.max_coverage_days_after,
        max_replenishment_per_article=payload.max_replenishment_per_article,
        article_ids=payload.article_ids,
        explanation=payload.explanation,
    )

    repl_items = compute_replenishment(db=db, payload=repl_request)

    now = datetime.now(timezone.utc)
    shipment = WbShipment(
        status="draft",
        target_date=payload.target_date,
        wb_arrival_date=payload.wb_arrival_date,
        comment=payload.comment,
        created_at=now,
        updated_at=now,
        strategy=repl_request.replenishment_strategy,
        zero_sales_policy=repl_request.zero_sales_policy,
        target_coverage_days=repl_request.target_coverage_days,
        min_coverage_days=repl_request.min_coverage_days,
        max_coverage_days_after=repl_request.max_coverage_days_after,
        max_replenishment_per_article=repl_request.max_replenishment_per_article,
    )
    db.add(shipment)
    db.flush()

    for it in repl_items:
        item = WbShipmentItem(
            shipment_id=shipment.id,
            article_id=it.article_id,
            color_id=it.color_id,
            size_id=it.size_id,
            wb_sku=it.wb_sku,
            recommended_qty=it.recommended_qty,
            final_qty=it.recommended_qty,
            nsk_stock_available=it.nsk_stock_available,
            oos_risk_before=it.oos_risk_before,
            oos_risk_after=it.oos_risk_after,
            limited_by_nsk_stock=it.limited_by_nsk_stock,
            limited_by_max_coverage=it.limited_by_max_coverage,
            ignored_due_to_zero_sales=it.ignored_due_to_zero_sales,
            below_min_coverage_threshold=it.below_min_coverage_threshold,
            article_total_deficit=it.article_total_deficit,
            article_total_recommended=it.article_total_recommended,
            explanation=it.explanation,
        )
        db.add(item)

    db.commit()
    db.refresh(shipment)
    return shipment
