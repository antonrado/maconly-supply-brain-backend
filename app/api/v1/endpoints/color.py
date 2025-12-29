from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Color
from app.schemas.color import ColorCreate, ColorRead, ColorUpdate


router = APIRouter()


@router.get("/", response_model=list[ColorRead])
def list_colors(db: Session = Depends(get_db)):
    colors = db.query(Color).all()
    return colors


@router.get("/{id}", response_model=ColorRead)
def get_color(id: int, db: Session = Depends(get_db)):
    color = db.query(Color).filter(Color.id == id).first()
    if color is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Color not found")
    return color


@router.post("/", response_model=ColorRead, status_code=status.HTTP_201_CREATED)
def create_color(data: ColorCreate, db: Session = Depends(get_db)):
    existing = db.query(Color).filter(Color.inner_code == data.inner_code).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Color inner_code already exists")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Color not found")

    if data.inner_code != color.inner_code:
        existing = db.query(Color).filter(Color.inner_code == data.inner_code, Color.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Color inner_code already exists")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Color not found")

    update_data = data.dict(exclude_unset=True)

    if "inner_code" in update_data:
        existing = db.query(Color).filter(Color.inner_code == update_data["inner_code"], Color.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Color inner_code already exists")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Color not found")

    db.delete(color)
    db.commit()
    return None
