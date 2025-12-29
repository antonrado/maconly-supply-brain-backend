from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import WbShipment, WbShipmentItem
from app.schemas.wb_shipment import (
    WbShipmentCreate,
    WbShipmentRead,
    WbShipmentUpdate,
    WbShipmentItemUpdate,
    WbShipmentHeaderRead,
    WbShipmentAggregates,
    WbShipmentItemSummary,
)
from app.schemas import WbShipmentPresetResponse
from app.services.wb_shipment import create_wb_shipment_from_proposal
from app.services.wb_shipment_preset import compute_shipment_preset


router = APIRouter()


WB_SHIPMENT_STATUS_ORDER: tuple[str, ...] = ("draft", "approved", "shipped", "cancelled")

_ALLOWED_STATUSES = set(WB_SHIPMENT_STATUS_ORDER)

_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "approved", "cancelled"},
    "approved": {"approved", "shipped", "cancelled"},
    "shipped": {"shipped"},
    "cancelled": {"cancelled"},
}


class WbShipmentStatusList(BaseModel):
    statuses: list[str]


@router.get(
    "/shipment/status-list",
    response_model=WbShipmentStatusList,
    tags=["WB Manager Public API"],
    summary="List WB shipment statuses",
    description="Returns the ordered list of shipment statuses used in WB Manager UI filters.",
)
def get_shipment_status_list() -> WbShipmentStatusList:
    return WbShipmentStatusList(statuses=list(WB_SHIPMENT_STATUS_ORDER))


@router.post(
    "/shipment/from-proposal",
    response_model=WbShipmentRead,
    status_code=status.HTTP_201_CREATED,
    tags=["WB Manager Public API"],
    summary="Create WB shipment from replenishment proposal",
    description=(
        "Recomputes the current replenishment proposal for the given parameters and "
        "persists it as a new draft WB shipment with editable items."
    ),
)
def create_shipment_from_proposal(
    payload: WbShipmentCreate,
    db: Session = Depends(get_db),
) -> WbShipment:
    if payload.wb_arrival_date < payload.target_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wb_arrival_date cannot be earlier than target_date",
        )

    shipment = create_wb_shipment_from_proposal(db=db, payload=payload)
    return shipment


@router.get("/shipment/", response_model=list[WbShipmentRead])
def list_shipments(
    status: str | None = Query(None),
    article_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[WbShipment]:
    query = db.query(WbShipment)
    if status is not None:
        query = query.filter(WbShipment.status == status)
    if date_from is not None:
        query = query.filter(WbShipment.target_date >= date_from)
    if date_to is not None:
        query = query.filter(WbShipment.target_date <= date_to)
    if article_id is not None:
        query = query.join(WbShipmentItem).filter(WbShipmentItem.article_id == article_id)

    shipments = query.all()
    return shipments


@router.get(
    "/shipment/headers",
    response_model=list[WbShipmentHeaderRead],
    tags=["WB Manager Public API"],
    summary="List WB shipment headers with aggregates",
    description=(
        "Returns shipment-level aggregates for use in the WB Manager shipments list, "
        "with optional filters, sorting and pagination."
    ),
)
def list_shipment_headers(
    status: str | None = Query(None),
    article_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[WbShipmentHeaderRead]:
    sortable_fields: dict[str, any] = {
        "id": WbShipment.id,
        "created_at": WbShipment.created_at,
        "updated_at": WbShipment.updated_at,
        "target_date": WbShipment.target_date,
        "wb_arrival_date": WbShipment.wb_arrival_date,
        "status": WbShipment.status,
    }
    if sort_by not in sortable_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by '{sort_by}', must be one of: {sorted(sortable_fields.keys())}",
        )

    sort_dir_normalized = sort_dir.lower()
    if sort_dir_normalized not in {"asc", "desc"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort_dir, must be 'asc' or 'desc'",
        )

    sort_column = sortable_fields[sort_by]
    order_expr = sort_column.asc() if sort_dir_normalized == "asc" else sort_column.desc()

    total_items_expr = func.count(WbShipmentItem.id)
    total_final_qty_expr = func.coalesce(func.sum(WbShipmentItem.final_qty), 0)
    red_risk_expr = func.coalesce(
        func.sum(case((WbShipmentItem.oos_risk_before == "red", 1), else_=0)), 0
    )
    yellow_risk_expr = func.coalesce(
        func.sum(case((WbShipmentItem.oos_risk_before == "yellow", 1), else_=0)), 0
    )

    query = (
        db.query(
            WbShipment.id,
            WbShipment.status,
            WbShipment.target_date,
            WbShipment.wb_arrival_date,
            WbShipment.comment,
            WbShipment.created_at,
            WbShipment.updated_at,
            total_final_qty_expr.label("total_final_qty"),
            total_items_expr.label("total_items"),
            red_risk_expr.label("red_risk_count"),
            yellow_risk_expr.label("yellow_risk_count"),
        )
        .outerjoin(WbShipmentItem, WbShipmentItem.shipment_id == WbShipment.id)
    )

    if status is not None:
        query = query.filter(WbShipment.status == status)
    if date_from is not None:
        query = query.filter(WbShipment.target_date >= date_from)
    if date_to is not None:
        query = query.filter(WbShipment.target_date <= date_to)
    if article_id is not None:
        query = query.filter(WbShipmentItem.article_id == article_id)

    query = query.group_by(
        WbShipment.id,
        WbShipment.status,
        WbShipment.target_date,
        WbShipment.wb_arrival_date,
        WbShipment.comment,
        WbShipment.created_at,
        WbShipment.updated_at,
    )
    query = query.order_by(order_expr).offset(offset).limit(limit)

    rows = query.all()
    result: list[WbShipmentHeaderRead] = []
    for row in rows:
        result.append(
            WbShipmentHeaderRead(
                id=row.id,
                status=row.status,
                target_date=row.target_date,
                wb_arrival_date=row.wb_arrival_date,
                comment=row.comment,
                created_at=row.created_at,
                updated_at=row.updated_at,
                total_final_qty=int(row.total_final_qty or 0),
                total_items=int(row.total_items or 0),
                red_risk_count=int(row.red_risk_count or 0),
                yellow_risk_count=int(row.yellow_risk_count or 0),
            )
        )

    return result


@router.get(
    "/shipment/{shipment_id}/aggregates",
    response_model=WbShipmentAggregates,
    tags=["WB Manager Public API"],
    summary="Get aggregates for a WB shipment",
    description="Returns item counts, total quantities and risk counts for a specific shipment.",
)
def get_shipment_aggregates(
    shipment_id: int,
    db: Session = Depends(get_db),
) -> WbShipmentAggregates:
    total_items_expr = func.count(WbShipmentItem.id)
    total_final_qty_expr = func.coalesce(func.sum(WbShipmentItem.final_qty), 0)
    red_risk_expr = func.coalesce(
        func.sum(case((WbShipmentItem.oos_risk_before == "red", 1), else_=0)), 0
    )
    yellow_risk_expr = func.coalesce(
        func.sum(case((WbShipmentItem.oos_risk_before == "yellow", 1), else_=0)), 0
    )

    row = (
        db.query(
            WbShipment.id.label("shipment_id"),
            WbShipment.status,
            WbShipment.created_at,
            WbShipment.updated_at,
            total_items_expr.label("total_items"),
            total_final_qty_expr.label("total_final_qty"),
            red_risk_expr.label("red_risk_count"),
            yellow_risk_expr.label("yellow_risk_count"),
        )
        .outerjoin(WbShipmentItem, WbShipmentItem.shipment_id == WbShipment.id)
        .filter(WbShipment.id == shipment_id)
        .group_by(
            WbShipment.id,
            WbShipment.status,
            WbShipment.created_at,
            WbShipment.updated_at,
        )
        .first()
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipment not found",
        )

    return WbShipmentAggregates(
        shipment_id=row.shipment_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        total_items=int(row.total_items or 0),
        total_final_qty=int(row.total_final_qty or 0),
        red_risk_count=int(row.red_risk_count or 0),
        yellow_risk_count=int(row.yellow_risk_count or 0),
    )


@router.get(
    "/shipment/preset",
    response_model=WbShipmentPresetResponse,
    tags=["WB Manager Public API"],
    summary="Get WB shipment preset parameters",
    description=(
        "Returns suggested parameters for creating a new WB shipment based on recent "
        "shipment history and typical transit times."
    ),
)
def get_shipment_preset(
    target_date: date = Query(
        ...,
        description="Date for which replenishment will be planned",
    ),
    db: Session = Depends(get_db),
) -> WbShipmentPresetResponse:
    """Returns default parameters for creating a new WB shipment based on shipment history."""
    preset = compute_shipment_preset(db=db, target_date=target_date)
    return preset


@router.get(
    "/shipment/{shipment_id}",
    response_model=WbShipmentRead,
    tags=["WB Manager Public API"],
    summary="Get WB shipment details",
    description="Returns full shipment header and items by ID for the WB Manager editor.",
)
def get_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
) -> WbShipment:
    shipment = db.query(WbShipment).filter(WbShipment.id == shipment_id).first()
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipment not found",
        )
    return shipment


@router.get(
    "/shipment/{shipment_id}/items/{item_id}/summary",
    response_model=WbShipmentItemSummary,
    tags=["WB Manager Public API"],
    summary="Get WB shipment item summary",
    description=(
        "Returns a detailed summary for a single shipment item, including explanation "
        "and risk flags, for use in the right-hand side inspector."
    ),
)
def get_shipment_item_summary(
    shipment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> WbShipmentItemSummary:
    shipment = db.query(WbShipment).filter(WbShipment.id == shipment_id).first()
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipment not found",
        )

    item = (
        db.query(WbShipmentItem)
        .filter(
            WbShipmentItem.id == item_id,
            WbShipmentItem.shipment_id == shipment_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipmentItem not found",
        )

    return WbShipmentItemSummary(
        item_id=item.id,
        shipment_id=item.shipment_id,
        article_id=item.article_id,
        color_id=item.color_id,
        size_id=item.size_id,
        wb_sku=item.wb_sku,
        recommended_qty=item.recommended_qty,
        final_qty=item.final_qty,
        nsk_stock_available=item.nsk_stock_available,
        oos_risk_before=item.oos_risk_before,
        oos_risk_after=item.oos_risk_after,
        limited_by_nsk_stock=item.limited_by_nsk_stock,
        limited_by_max_coverage=item.limited_by_max_coverage,
        ignored_due_to_zero_sales=item.ignored_due_to_zero_sales,
        below_min_coverage_threshold=item.below_min_coverage_threshold,
        article_total_deficit=item.article_total_deficit,
        article_total_recommended=item.article_total_recommended,
        explanation=item.explanation,
    )


@router.patch(
    "/shipment/{shipment_id}",
    response_model=WbShipmentRead,
    tags=["WB Manager Public API"],
    summary="Update WB shipment header",
    description="Updates status and/or comment of a shipment while enforcing status transitions.",
)
def update_shipment(
    shipment_id: int,
    payload: WbShipmentUpdate,
    db: Session = Depends(get_db),
) -> WbShipment:
    shipment = db.query(WbShipment).filter(WbShipment.id == shipment_id).first()
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipment not found",
        )

    if shipment.status in {"shipped", "cancelled"}:
        # Final states: no further modifications allowed
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a shipment in final status",
        )

    data = payload.dict(exclude_unset=True)
    changed = False

    if "status" in data:
        new_status = data["status"]
        if new_status not in _ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{new_status}', must be one of: {sorted(_ALLOWED_STATUSES)}",
            )
        old_status = shipment.status
        allowed_targets = _ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
        if new_status not in allowed_targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition from '{old_status}' to '{new_status}'",
            )
        if new_status != old_status:
            shipment.status = new_status
            changed = True

    if "comment" in data:
        if data["comment"] != shipment.comment:
            shipment.comment = data["comment"]
            changed = True

    if changed:
        shipment.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(shipment)
    return shipment


@router.patch(
    "/shipment/{shipment_id}/items/{item_id}",
    response_model=WbShipmentRead,
    tags=["WB Manager Public API"],
    summary="Update a WB shipment item",
    description="Updates final quantity and explanation for a single shipment item in draft shipments only.",
)
def update_shipment_item(
    shipment_id: int,
    item_id: int,
    payload: WbShipmentItemUpdate,
    db: Session = Depends(get_db),
) -> WbShipment:
    shipment = db.query(WbShipment).filter(WbShipment.id == shipment_id).first()
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipment not found",
        )

    if shipment.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify items of a non-draft shipment",
        )

    item = (
        db.query(WbShipmentItem)
        .filter(
            WbShipmentItem.id == item_id,
            WbShipmentItem.shipment_id == shipment_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WbShipmentItem not found",
        )

    data = payload.dict(exclude_unset=True)
    if "final_qty" in data:
        new_final_qty = int(data["final_qty"])
        if new_final_qty > item.nsk_stock_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="final_qty exceeds available NSC stock",
            )
        item.final_qty = new_final_qty
    if "explanation" in data:
        item.explanation = data["explanation"]

    shipment.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(shipment)
    return shipment
