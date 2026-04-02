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


def _build_planning_settings_not_found_detail(*, planning_settings_id: int) -> dict[str, object]:
    return {
        "code": "planning_settings_not_found",
        "message": "PlanningSettings not found",
        "planning_settings_id": int(planning_settings_id),
        "next_steps": ["use_existing_planning_settings_id"],
    }


def _build_planning_settings_article_already_exists_detail(*, article_id: int) -> dict[str, object]:
    return {
        "code": "planning_settings_article_already_exists",
        "message": "PlanningSettings for this article already exists",
        "field": "article_id",
        "article_id": int(article_id),
        "next_steps": ["use_article_without_existing_planning_settings"],
    }


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
            detail=_build_planning_settings_not_found_detail(planning_settings_id=id),
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
            detail=_build_planning_settings_article_already_exists_detail(article_id=data.article_id),
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
            detail=_build_planning_settings_not_found_detail(planning_settings_id=id),
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
                detail=_build_planning_settings_article_already_exists_detail(article_id=data.article_id),
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
            detail=_build_planning_settings_not_found_detail(planning_settings_id=id),
        )

    update_data = data.model_dump(exclude_unset=True)

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
                detail=_build_planning_settings_article_already_exists_detail(article_id=new_article_id),
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
            detail=_build_planning_settings_not_found_detail(planning_settings_id=id),
        )

    db.delete(item)
    db.commit()
    return None
