from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import BundleRecipe
from app.schemas.bundle_recipe import BundleRecipeCreate, BundleRecipeRead, BundleRecipeUpdate


router = APIRouter()


def _ensure_unique_constraints(
    db: Session,
    article_id: int,
    bundle_type_id: int,
    color_id: int,
    position: int,
    current_id: int | None = None,
) -> None:
    q = db.query(BundleRecipe)

    q_color = q.filter(
        BundleRecipe.article_id == article_id,
        BundleRecipe.bundle_type_id == bundle_type_id,
        BundleRecipe.color_id == color_id,
    )
    q_position = q.filter(
        BundleRecipe.article_id == article_id,
        BundleRecipe.bundle_type_id == bundle_type_id,
        BundleRecipe.position == position,
    )

    if current_id is not None:
        q_color = q_color.filter(BundleRecipe.id != current_id)
        q_position = q_position.filter(BundleRecipe.id != current_id)

    if q_color.first() is not None or q_position.first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="BundleRecipe with same combination already exists")


@router.get("/", response_model=list[BundleRecipeRead])
def list_bundle_recipes(db: Session = Depends(get_db)):
    items = db.query(BundleRecipe).all()
    return items


@router.get("/{id}", response_model=BundleRecipeRead)
def get_bundle_recipe(id: int, db: Session = Depends(get_db)):
    item = db.query(BundleRecipe).filter(BundleRecipe.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleRecipe not found")
    return item


@router.post("/", response_model=BundleRecipeRead, status_code=status.HTTP_201_CREATED)
def create_bundle_recipe(data: BundleRecipeCreate, db: Session = Depends(get_db)):
    _ensure_unique_constraints(
        db,
        article_id=data.article_id,
        bundle_type_id=data.bundle_type_id,
        color_id=data.color_id,
        position=data.position,
    )

    item = BundleRecipe(
        article_id=data.article_id,
        bundle_type_id=data.bundle_type_id,
        color_id=data.color_id,
        position=data.position,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{id}", response_model=BundleRecipeRead)
def update_bundle_recipe(id: int, data: BundleRecipeCreate, db: Session = Depends(get_db)):
    item = db.query(BundleRecipe).filter(BundleRecipe.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleRecipe not found")

    _ensure_unique_constraints(
        db,
        article_id=data.article_id,
        bundle_type_id=data.bundle_type_id,
        color_id=data.color_id,
        position=data.position,
        current_id=id,
    )

    item.article_id = data.article_id
    item.bundle_type_id = data.bundle_type_id
    item.color_id = data.color_id
    item.position = data.position
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{id}", response_model=BundleRecipeRead)
def partial_update_bundle_recipe(id: int, data: BundleRecipeUpdate, db: Session = Depends(get_db)):
    item = db.query(BundleRecipe).filter(BundleRecipe.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleRecipe not found")

    update_data = data.dict(exclude_unset=True)

    new_article_id = update_data.get("article_id", item.article_id)
    new_bundle_type_id = update_data.get("bundle_type_id", item.bundle_type_id)
    new_color_id = update_data.get("color_id", item.color_id)
    new_position = update_data.get("position", item.position)

    _ensure_unique_constraints(
        db,
        article_id=new_article_id,
        bundle_type_id=new_bundle_type_id,
        color_id=new_color_id,
        position=new_position,
        current_id=id,
    )

    item.article_id = new_article_id
    item.bundle_type_id = new_bundle_type_id
    item.color_id = new_color_id
    item.position = new_position
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bundle_recipe(id: int, db: Session = Depends(get_db)):
    item = db.query(BundleRecipe).filter(BundleRecipe.id == id).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleRecipe not found")

    db.delete(item)
    db.commit()
    return None
