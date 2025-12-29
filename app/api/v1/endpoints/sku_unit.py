from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import SkuUnit
from app.schemas.sku_unit import SkuUnitCreate, SkuUnitRead, SkuUnitUpdate


router = APIRouter()


def _ensure_unique_combination(db: Session, article_id: int, color_id: int, size_id: int, current_id: int | None = None) -> None:
    query = db.query(SkuUnit).filter(
        SkuUnit.article_id == article_id,
        SkuUnit.color_id == color_id,
        SkuUnit.size_id == size_id,
    )
    if current_id is not None:
        query = query.filter(SkuUnit.id != current_id)
    existing = query.first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SkuUnit combination already exists")


@router.get("/", response_model=list[SkuUnitRead])
def list_sku_units(db: Session = Depends(get_db)):
    items = db.query(SkuUnit).all()
    return items


@router.get("/{id}", response_model=SkuUnitRead)
def get_sku_unit(id: int, db: Session = Depends(get_db)):
    item = db.query(SkuUnit).filter(SkuUnit.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SkuUnit not found")
    return item


@router.post("/", response_model=SkuUnitRead, status_code=status.HTTP_201_CREATED)
def create_sku_unit(data: SkuUnitCreate, db: Session = Depends(get_db)):
    _ensure_unique_combination(db, data.article_id, data.color_id, data.size_id)

    item = SkuUnit(
        article_id=data.article_id,
        color_id=data.color_id,
        size_id=data.size_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=SkuUnitRead)
def update_sku_unit(id: int, data: SkuUnitCreate, db: Session = Depends(get_db)):
    item = db.query(SkuUnit).filter(SkuUnit.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SkuUnit not found")

    _ensure_unique_combination(db, data.article_id, data.color_id, data.size_id, current_id=id)

    item.article_id = data.article_id
    item.color_id = data.color_id
    item.size_id = data.size_id
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=SkuUnitRead)
def partial_update_sku_unit(id: int, data: SkuUnitUpdate, db: Session = Depends(get_db)):
    item = db.query(SkuUnit).filter(SkuUnit.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SkuUnit not found")

    update_data = data.dict(exclude_unset=True)

    new_article_id = update_data.get("article_id", item.article_id)
    new_color_id = update_data.get("color_id", item.color_id)
    new_size_id = update_data.get("size_id", item.size_id)

    _ensure_unique_combination(db, new_article_id, new_color_id, new_size_id, current_id=id)

    item.article_id = new_article_id
    item.color_id = new_color_id
    item.size_id = new_size_id
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sku_unit(id: int, db: Session = Depends(get_db)):
    item = db.query(SkuUnit).filter(SkuUnit.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SkuUnit not found")

    db.delete(item)
    db.commit()
    return None
