from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Size
from app.schemas.size import SizeBase, SizeCreate, SizeRead, SizeUpdate


router = APIRouter()


def _build_size_not_found_detail(*, size_id: int) -> dict[str, object]:
    return {
        "code": "size_not_found",
        "message": "Size not found",
        "size_id": int(size_id),
        "field": "size_id",
        "field_metadata": {
            "description": "Requested size identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_size_id"],
    }


def _build_size_label_already_exists_detail(*, size_label: str) -> dict[str, object]:
    return {
        "code": "size_label_already_exists",
        "message": "Size label already exists",
        "field": "label",
        "field_metadata": {
            "description": "Requested size label",
            "type": "string",
        },
        "size_label": str(size_label),
        "next_steps": ["use_unique_size_label"],
    }


@router.get("/", response_model=list[SizeRead])
def list_sizes(db: Session = Depends(get_db)):
    sizes = db.query(Size).all()
    return sizes


@router.get("/{id}", response_model=SizeRead)
def get_size(id: int, db: Session = Depends(get_db)):
    size = db.query(Size).filter(Size.id == id).first()
    if size is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_size_not_found_detail(size_id=id),
        )
    return size


@router.post("/", response_model=SizeRead, status_code=status.HTTP_201_CREATED)
def create_size(data: SizeCreate, db: Session = Depends(get_db)):
    existing = db.query(Size).filter(Size.label == data.label).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_build_size_label_already_exists_detail(size_label=data.label),
        )

    size = Size(label=data.label, sort_order=data.sort_order)
    db.add(size)
    db.commit()
    db.refresh(size)
    return size


@router.put("/{id}", response_model=SizeRead)
def update_size(id: int, data: SizeCreate, db: Session = Depends(get_db)):
    size = db.query(Size).filter(Size.id == id).first()
    if size is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_size_not_found_detail(size_id=id),
        )

    if data.label != size.label:
        existing = db.query(Size).filter(Size.label == data.label, Size.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_size_label_already_exists_detail(size_label=data.label),
            )

    size.label = data.label
    size.sort_order = data.sort_order
    db.commit()
    db.refresh(size)
    return size


@router.patch("/{id}", response_model=SizeRead)
def partial_update_size(id: int, data: SizeUpdate, db: Session = Depends(get_db)):
    size = db.query(Size).filter(Size.id == id).first()
    if size is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_size_not_found_detail(size_id=id),
        )

    update_data = data.model_dump(exclude_unset=True)

    if "label" in update_data:
        existing = db.query(Size).filter(Size.label == update_data["label"], Size.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_size_label_already_exists_detail(size_label=update_data["label"]),
            )
        size.label = update_data["label"]

    if "sort_order" in update_data:
        size.sort_order = update_data["sort_order"]

    db.commit()
    db.refresh(size)
    return size


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_size(id: int, db: Session = Depends(get_db)):
    size = db.query(Size).filter(Size.id == id).first()
    if size is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_size_not_found_detail(size_id=id),
        )

    db.delete(size)
    db.commit()
    return None
