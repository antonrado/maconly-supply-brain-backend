from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Warehouse
from app.schemas.warehouse import WarehouseCreate, WarehouseRead, WarehouseUpdate


router = APIRouter()


def _build_warehouse_not_found_detail(*, warehouse_id: int) -> dict[str, object]:
    return {
        "code": "warehouse_not_found",
        "message": "Warehouse not found",
        "warehouse_id": int(warehouse_id),
        "field": "warehouse_id",
        "field_metadata": {
            "description": "Requested warehouse identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_warehouse_id"],
    }


def _build_warehouse_code_already_exists_detail(*, warehouse_code: str) -> dict[str, object]:
    return {
        "code": "warehouse_code_already_exists",
        "message": "Warehouse code already exists",
        "field": "code",
        "field_metadata": {
            "description": "Requested warehouse code",
            "type": "string",
        },
        "warehouse_code": str(warehouse_code),
        "next_steps": ["use_unique_warehouse_code"],
    }


@router.get("/", response_model=list[WarehouseRead])
def list_warehouses(db: Session = Depends(get_db)):
    items = db.query(Warehouse).all()
    return items


@router.get("/{id}", response_model=WarehouseRead)
def get_warehouse(id: int, db: Session = Depends(get_db)):
    item = db.query(Warehouse).filter(Warehouse.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_warehouse_not_found_detail(warehouse_id=id),
        )
    return item


@router.post("/", response_model=WarehouseRead, status_code=status.HTTP_201_CREATED)
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db)):
    existing = db.query(Warehouse).filter(Warehouse.code == data.code).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_build_warehouse_code_already_exists_detail(warehouse_code=data.code),
        )

    item = Warehouse(code=data.code, name=data.name, type=data.type)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=WarehouseRead)
def update_warehouse(id: int, data: WarehouseCreate, db: Session = Depends(get_db)):
    item = db.query(Warehouse).filter(Warehouse.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_warehouse_not_found_detail(warehouse_id=id),
        )

    if data.code != item.code:
        existing = db.query(Warehouse).filter(Warehouse.code == data.code, Warehouse.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_warehouse_code_already_exists_detail(warehouse_code=data.code),
            )

    item.code = data.code
    item.name = data.name
    item.type = data.type
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=WarehouseRead)
def partial_update_warehouse(id: int, data: WarehouseUpdate, db: Session = Depends(get_db)):
    item = db.query(Warehouse).filter(Warehouse.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_warehouse_not_found_detail(warehouse_id=id),
        )

    update_data = data.model_dump(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(Warehouse).filter(Warehouse.code == update_data["code"], Warehouse.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_warehouse_code_already_exists_detail(warehouse_code=update_data["code"]),
            )
        item.code = update_data["code"]

    if "name" in update_data:
        item.name = update_data["name"]

    if "type" in update_data:
        item.type = update_data["type"]

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_warehouse(id: int, db: Session = Depends(get_db)):
    item = db.query(Warehouse).filter(Warehouse.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_warehouse_not_found_detail(warehouse_id=id),
        )

    db.delete(item)
    db.commit()
    return None
