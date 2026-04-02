from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Color
from app.schemas.color import ColorCreate, ColorRead, ColorUpdate


router = APIRouter()


def _build_color_not_found_detail(*, color_id: int) -> dict[str, object]:
    return {
        "code": "color_not_found",
        "message": "Color not found",
        "color_id": int(color_id),
        "next_steps": ["use_existing_color_id"],
    }


def _build_color_inner_code_already_exists_detail(*, inner_code: str) -> dict[str, object]:
    return {
        "code": "color_inner_code_already_exists",
        "message": "Color inner_code already exists",
        "field": "inner_code",
        "inner_code": str(inner_code),
        "next_steps": ["use_unique_color_inner_code"],
    }


@router.get("/", response_model=list[ColorRead])
def list_colors(db: Session = Depends(get_db)):
    colors = db.query(Color).all()
    return colors


@router.get("/{id}", response_model=ColorRead)
def get_color(id: int, db: Session = Depends(get_db)):
    color = db.query(Color).filter(Color.id == id).first()
    if color is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_color_not_found_detail(color_id=id),
        )
    return color


@router.post("/", response_model=ColorRead, status_code=status.HTTP_201_CREATED)
def create_color(data: ColorCreate, db: Session = Depends(get_db)):
    existing = db.query(Color).filter(Color.inner_code == data.inner_code).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_build_color_inner_code_already_exists_detail(inner_code=data.inner_code),
        )

    color = Color(
        pantone_code=data.pantone_code,
        inner_code=data.inner_code,
        description=data.description,
    )
    db.add(color)
    db.commit()
    db.refresh(color)
    return color


@router.put("/{id}", response_model=ColorRead)
def update_color(id: int, data: ColorCreate, db: Session = Depends(get_db)):
    color = db.query(Color).filter(Color.id == id).first()
    if color is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_color_not_found_detail(color_id=id),
        )

    if data.inner_code != color.inner_code:
        existing = db.query(Color).filter(Color.inner_code == data.inner_code, Color.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_color_inner_code_already_exists_detail(inner_code=data.inner_code),
            )

    color.pantone_code = data.pantone_code
    color.inner_code = data.inner_code
    color.description = data.description
    db.commit()
    db.refresh(color)
    return color


@router.patch("/{id}", response_model=ColorRead)
def partial_update_color(id: int, data: ColorUpdate, db: Session = Depends(get_db)):
    color = db.query(Color).filter(Color.id == id).first()
    if color is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_color_not_found_detail(color_id=id),
        )

    update_data = data.model_dump(exclude_unset=True)

    if "inner_code" in update_data:
        existing = db.query(Color).filter(Color.inner_code == update_data["inner_code"], Color.id != id).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_build_color_inner_code_already_exists_detail(inner_code=update_data["inner_code"]),
            )
        color.inner_code = update_data["inner_code"]

    if "pantone_code" in update_data:
        color.pantone_code = update_data["pantone_code"]

    if "description" in update_data:
        color.description = update_data["description"]

    db.commit()
    db.refresh(color)
    return color


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_color(id: int, db: Session = Depends(get_db)):
    color = db.query(Color).filter(Color.id == id).first()
    if color is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_color_not_found_detail(color_id=id),
        )

    db.delete(color)
    db.commit()
    return None
