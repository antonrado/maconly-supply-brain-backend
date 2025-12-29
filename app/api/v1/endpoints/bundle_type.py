from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import BundleType
from app.schemas.bundle_type import BundleTypeCreate, BundleTypeRead, BundleTypeUpdate


router = APIRouter()


@router.get("/", response_model=list[BundleTypeRead])
def list_bundle_types(db: Session = Depends(get_db)):
    items = db.query(BundleType).all()
    return items


@router.get("/{id}", response_model=BundleTypeRead)
def get_bundle_type(id: int, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleType not found")
    return item


@router.post("/", response_model=BundleTypeRead, status_code=status.HTTP_201_CREATED)
def create_bundle_type(data: BundleTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(BundleType).filter(BundleType.code == data.code).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BundleType code already exists")

    item = BundleType(code=data.code, name=data.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=BundleTypeRead)
def update_bundle_type(id: int, data: BundleTypeCreate, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleType not found")

    if data.code != item.code:
        existing = db.query(BundleType).filter(BundleType.code == data.code, BundleType.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BundleType code already exists")

    item.code = data.code
    item.name = data.name
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=BundleTypeRead)
def partial_update_bundle_type(id: int, data: BundleTypeUpdate, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleType not found")

    update_data = data.dict(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(BundleType).filter(BundleType.code == update_data["code"], BundleType.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BundleType code already exists")
        item.code = update_data["code"]

    if "name" in update_data:
        item.name = update_data["name"]

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bundle_type(id: int, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleType not found")

    db.delete(item)
    db.commit()
    return None
