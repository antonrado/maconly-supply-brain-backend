from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import StockBalance
from app.schemas.stock_balance import (
    StockBalanceCreate,
    StockBalanceRead,
    StockBalanceUpdate,
)


router = APIRouter()


def _ensure_unique_pair(
    db: Session,
    sku_unit_id: int,
    warehouse_id: int,
    current_id: int | None = None,
) -> None:
    query = db.query(StockBalance).filter(
        StockBalance.sku_unit_id == sku_unit_id,
        StockBalance.warehouse_id == warehouse_id,
    )
    if current_id is not None:
        query = query.filter(StockBalance.id != current_id)
    existing = query.first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="StockBalance for this sku_unit and warehouse already exists",
        )


@router.get("/", response_model=list[StockBalanceRead])
def list_stock_balances(db: Session = Depends(get_db)):
    items = db.query(StockBalance).all()
    return items


@router.get("/{id}", response_model=StockBalanceRead)
def get_stock_balance(id: int, db: Session = Depends(get_db)):
    item = db.query(StockBalance).filter(StockBalance.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="StockBalance not found"
        )
    return item


@router.post("/", response_model=StockBalanceRead, status_code=status.HTTP_201_CREATED)
def create_stock_balance(data: StockBalanceCreate, db: Session = Depends(get_db)):
    _ensure_unique_pair(db, data.sku_unit_id, data.warehouse_id)

    updated_at = data.updated_at or datetime.now(timezone.utc)

    item = StockBalance(
        sku_unit_id=data.sku_unit_id,
        warehouse_id=data.warehouse_id,
        quantity=data.quantity,
        updated_at=updated_at,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=StockBalanceRead)
def update_stock_balance(
    id: int, data: StockBalanceCreate, db: Session = Depends(get_db)
):
    item = db.query(StockBalance).filter(StockBalance.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="StockBalance not found"
        )

    _ensure_unique_pair(db, data.sku_unit_id, data.warehouse_id, current_id=id)

    # If updated_at is not provided, keep the existing value
    new_updated_at = data.updated_at or item.updated_at

    item.sku_unit_id = data.sku_unit_id
    item.warehouse_id = data.warehouse_id
    item.quantity = data.quantity
    item.updated_at = new_updated_at
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=StockBalanceRead)
def partial_update_stock_balance(
    id: int, data: StockBalanceUpdate, db: Session = Depends(get_db)
):
    item = db.query(StockBalance).filter(StockBalance.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="StockBalance not found"
        )

    update_data = data.dict(exclude_unset=True)

    new_sku_unit_id = update_data.get("sku_unit_id", item.sku_unit_id)
    new_warehouse_id = update_data.get("warehouse_id", item.warehouse_id)

    _ensure_unique_pair(db, new_sku_unit_id, new_warehouse_id, current_id=id)

    item.sku_unit_id = new_sku_unit_id
    item.warehouse_id = new_warehouse_id
    if "quantity" in update_data:
        item.quantity = update_data["quantity"]
    if "updated_at" in update_data:
        item.updated_at = update_data["updated_at"]

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock_balance(id: int, db: Session = Depends(get_db)):
    item = db.query(StockBalance).filter(StockBalance.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="StockBalance not found"
        )

    db.delete(item)
    db.commit()
    return None
