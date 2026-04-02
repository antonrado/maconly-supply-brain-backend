from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import BundleType
from app.schemas.bundle_type import BundleTypeCreate, BundleTypeRead, BundleTypeUpdate


router = APIRouter()


def _build_bundle_type_not_found_detail(*, bundle_type_id: int) -> dict[str, object]:
    return {
        "code": "bundle_type_not_found",
        "message": "BundleType not found",
        "bundle_type_id": int(bundle_type_id),
        "next_steps": ["use_existing_bundle_type_id"],
    }


def _build_bundle_type_code_already_exists_detail(*, bundle_type_code: str) -> dict[str, object]:
    return {
        "code": "bundle_type_code_already_exists",
        "message": "BundleType code already exists",
        "field": "code",
        "bundle_type_code": str(bundle_type_code),
        "next_steps": ["use_unique_bundle_type_code"],
    }


@router.get("/", response_model=list[BundleTypeRead])
def list_bundle_types(db: Session = Depends(get_db)):
    items = db.query(BundleType).all()
    return items


@router.get("/{id}", response_model=BundleTypeRead)
def get_bundle_type(id: int, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_bundle_type_not_found_detail(bundle_type_id=id),
        )
    return item


@router.post("/", response_model=BundleTypeRead, status_code=status.HTTP_201_CREATED)
def create_bundle_type(data: BundleTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(BundleType).filter(BundleType.code == data.code).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_build_bundle_type_code_already_exists_detail(bundle_type_code=data.code),
        )

    item = BundleType(code=data.code, name=data.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=BundleTypeRead)
def update_bundle_type(id: int, data: BundleTypeCreate, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_bundle_type_not_found_detail(bundle_type_id=id),
        )

    if data.code != item.code:
        existing = db.query(BundleType).filter(BundleType.code == data.code, BundleType.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_bundle_type_code_already_exists_detail(bundle_type_code=data.code),
            )

    item.code = data.code
    item.name = data.name
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=BundleTypeRead)
def partial_update_bundle_type(id: int, data: BundleTypeUpdate, db: Session = Depends(get_db)):
    item = db.query(BundleType).filter(BundleType.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_bundle_type_not_found_detail(bundle_type_id=id),
        )

    update_data = data.model_dump(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(BundleType).filter(BundleType.code == update_data["code"], BundleType.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_bundle_type_code_already_exists_detail(bundle_type_code=update_data["code"]),
            )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_bundle_type_not_found_detail(bundle_type_id=id),
        )

    db.delete(item)
    db.commit()
    return None
