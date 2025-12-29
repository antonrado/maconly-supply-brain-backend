from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import PlanningSettings
from app.schemas.planning_settings import (
    PlanningSettingsCreate,
    PlanningSettingsRead,
    PlanningSettingsUpdate,
)


router = APIRouter()


@router.get("/", response_model=list[PlanningSettingsRead])
def list_planning_settings(db: Session = Depends(get_db)):
    items = db.query(PlanningSettings).all()
    return items


@router.get("/{id}", response_model=PlanningSettingsRead)
def get_planning_settings(id: int, db: Session = Depends(get_db)):
    item = db.query(PlanningSettings).filter(PlanningSettings.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PlanningSettings not found",
        )
    return item


@router.post("/", response_model=PlanningSettingsRead, status_code=status.HTTP_201_CREATED)
def create_planning_settings(
    data: PlanningSettingsCreate,
    db: Session = Depends(get_db),
):
    existing = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == data.article_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PlanningSettings for this article already exists",
        )

    item = PlanningSettings(
        article_id=data.article_id,
        is_active=data.is_active,
        min_fabric_batch=data.min_fabric_batch,
        min_elastic_batch=data.min_elastic_batch,
        alert_threshold_days=data.alert_threshold_days,
        safety_stock_days=data.safety_stock_days,
        strictness=data.strictness,
        notes=data.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=PlanningSettingsRead)
def update_planning_settings(
    id: int,
    data: PlanningSettingsCreate,
    db: Session = Depends(get_db),
):
    item = db.query(PlanningSettings).filter(PlanningSettings.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PlanningSettings not found",
        )

    if data.article_id != item.article_id:
        existing = (
            db.query(PlanningSettings)
            .filter(
                PlanningSettings.article_id == data.article_id,
                PlanningSettings.id != id,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PlanningSettings for this article already exists",
            )

    item.article_id = data.article_id
    item.is_active = data.is_active
    item.min_fabric_batch = data.min_fabric_batch
    item.min_elastic_batch = data.min_elastic_batch
    item.alert_threshold_days = data.alert_threshold_days
    item.safety_stock_days = data.safety_stock_days
    item.strictness = data.strictness
    item.notes = data.notes
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=PlanningSettingsRead)
def partial_update_planning_settings(
    id: int,
    data: PlanningSettingsUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(PlanningSettings).filter(PlanningSettings.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PlanningSettings not found",
        )

    update_data = data.dict(exclude_unset=True)

    if "article_id" in update_data:
        new_article_id = update_data["article_id"]
        existing = (
            db.query(PlanningSettings)
            .filter(
                PlanningSettings.article_id == new_article_id,
                PlanningSettings.id != id,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PlanningSettings for this article already exists",
            )
        item.article_id = new_article_id

    for field in [
        "is_active",
        "min_fabric_batch",
        "min_elastic_batch",
        "alert_threshold_days",
        "safety_stock_days",
        "strictness",
        "notes",
    ]:
        if field in update_data:
            setattr(item, field, update_data[field])

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planning_settings(id: int, db: Session = Depends(get_db)):
    item = db.query(PlanningSettings).filter(PlanningSettings.id == id).first()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PlanningSettings not found",
        )

    db.delete(item)
    db.commit()
    return None
