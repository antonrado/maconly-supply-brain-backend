from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    BundleRecipe,
    BundleType,
    Size,
    SkuUnit,
    StockBalance,
    Warehouse,
)
from app.schemas.bundle_deficit import DeficitPerSize, BundleDeficitResponse


def calculate_bundle_deficit(
    db: Session,
    article_id: int,
    bundle_type_id: int,
    warehouse_id: int,
    target_count: int,
) -> BundleDeficitResponse:
    if target_count <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_count must be positive",
        )

    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    bundle_type = db.query(BundleType).filter(BundleType.id == bundle_type_id).first()
    if bundle_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BundleType not found")

    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if warehouse is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found")

    recipes = (
        db.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == article_id,
            BundleRecipe.bundle_type_id == bundle_type_id,
        )
        .all()
    )

    if not recipes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No bundle recipe defined for this article and bundle type",
        )

    recipe_color_ids = {r.color_id for r in recipes}

    sku_units = (
        db.query(SkuUnit)
        .filter(
            SkuUnit.article_id == article_id,
            SkuUnit.color_id.in_(recipe_color_ids),
        )
        .all()
    )

    size_to_color_sku: dict[int, dict[int, SkuUnit]] = defaultdict(dict)
    for sku in sku_units:
        size_to_color_sku[sku.size_id][sku.color_id] = sku

    size_ids = list(size_to_color_sku.keys())
    sizes = db.query(Size).filter(Size.id.in_(size_ids)).all() if size_ids else []
    size_map = {s.id: s for s in sizes}

    balances = (
        db.query(StockBalance)
        .filter(
            StockBalance.warehouse_id == warehouse_id,
            StockBalance.sku_unit_id.in_([sku.id for sku in sku_units]) if sku_units else False,
        )
        .all()
        if sku_units
        else []
    )
    balance_map: dict[int, int] = {b.sku_unit_id: b.quantity for b in balances}

    per_size: list[DeficitPerSize] = []
    total_deficit_per_color: dict[int, int] = {color_id: 0 for color_id in recipe_color_ids}

    for size_id, color_sku_map in size_to_color_sku.items():
        size_obj = size_map.get(size_id)
        size_label = size_obj.label if size_obj is not None else str(size_id)

        required: dict[int, int] = {}
        current: dict[int, int] = {}
        deficit: dict[int, int] = {}

        for color_id in recipe_color_ids:
            req = target_count
            sku_unit = color_sku_map.get(color_id)
            cur = 0
            if sku_unit is not None:
                cur = balance_map.get(sku_unit.id, 0)

            diff = max(req - cur, 0)

            required[color_id] = req
            current[color_id] = cur
            deficit[color_id] = diff

            total_deficit_per_color[color_id] = total_deficit_per_color.get(color_id, 0) + diff

        per_size.append(
            DeficitPerSize(
                size_id=size_id,
                size_label=size_label,
                required=required,
                current=current,
                deficit=deficit,
            )
        )

    return BundleDeficitResponse(
        article_id=article_id,
        bundle_type_id=bundle_type_id,
        warehouse_id=warehouse_id,
        target_count=target_count,
        per_size=per_size,
        total_deficit_per_color=total_deficit_per_color,
    )
