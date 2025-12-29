from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import PurchaseOrder, PurchaseOrderItem
from app.schemas.purchase_order import (
    PurchaseOrderFromProposalRequest,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)
from app.services.purchase_order import create_purchase_order_from_proposal


router = APIRouter()


@router.post("/from-proposal", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
def create_from_proposal(
    payload: PurchaseOrderFromProposalRequest,
    db: Session = Depends(get_db),
) -> PurchaseOrder:
    po = create_purchase_order_from_proposal(
        db=db,
        target_date=payload.target_date,
        explanation=payload.explanation,
        comment=payload.comment,
    )
    return po


@router.get("/", response_model=list[PurchaseOrderRead])
def list_purchase_orders(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[PurchaseOrder]:
    query = db.query(PurchaseOrder)
    if status_filter is not None:
        query = query.filter(PurchaseOrder.status == status_filter)
    orders = query.offset(offset).limit(limit).all()
    return orders


@router.get("/{order_id}", response_model=PurchaseOrderRead)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)) -> PurchaseOrder:
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PurchaseOrder not found")
    return po


_ALLOWED_STATUSES = {"draft", "approved", "cancelled"}

_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "approved", "cancelled"},
    "approved": {"approved", "cancelled"},
    "cancelled": {"cancelled"},
}


@router.patch("/{order_id}", response_model=PurchaseOrderRead)
def update_purchase_order(
    order_id: int,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
) -> PurchaseOrder:
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PurchaseOrder not found")

    data = payload.dict(exclude_unset=True)

    changed = False

    if "status" in data:
        new_status = data["status"]
        if new_status not in _ALLOWED_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status '{new_status}', must be one of: {sorted(_ALLOWED_STATUSES)}",
            )
        old_status = po.status
        allowed_targets = _ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
        if new_status not in allowed_targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition from '{old_status}' to '{new_status}'",
            )
        if new_status != old_status:
            po.status = new_status
            changed = True

    if "comment" in data:
        if data["comment"] != po.comment:
            po.comment = data["comment"]
            changed = True

    if "external_ref" in data:
        if data["external_ref"] != po.external_ref:
            po.external_ref = data["external_ref"]
            changed = True

    if changed:
        po.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(po)
    return po


@router.patch("/{order_id}/items/{item_id}", response_model=PurchaseOrderRead)
def update_purchase_order_item(
    order_id: int,
    item_id: int,
    payload: dict,
    db: Session = Depends(get_db),
) -> PurchaseOrder:
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if po is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PurchaseOrder not found")

    if po.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify items of a non-draft purchase order",
        )

    item = (
        db.query(PurchaseOrderItem)
        .filter(
            PurchaseOrderItem.id == item_id,
            PurchaseOrderItem.purchase_order_id == order_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PurchaseOrderItem not found")

    # Minimal v1 behavior: allow updating quantity and notes if provided
    if "quantity" in payload:
        item.quantity = int(payload["quantity"])
    if "notes" in payload:
        item.notes = payload["notes"]

    po.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(po)
    return po
