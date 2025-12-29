from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.bundle_deficit import BundleDeficitResponse
from app.services.bundle_deficit import calculate_bundle_deficit

router = APIRouter()


@router.get(
    "/bundle-deficit",
    response_model=BundleDeficitResponse,
)
def get_bundle_deficit(
    article_id: int,
    bundle_type_id: int,
    warehouse_id: int,
    target_count: int,
    db: Session = Depends(get_db),
):
    return calculate_bundle_deficit(
        db=db,
        article_id=article_id,
        bundle_type_id=bundle_type_id,
        warehouse_id=warehouse_id,
        target_count=target_count,
    )
