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
from app.schemas.planning import BundleAvailabilityPerSize, BundleAvailabilityResponse


def _build_article_not_found_detail(*, article_id: int) -> dict[str, object]:
    return {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": int(article_id),
        "next_steps": ["use_existing_article_id"],
    }


def _build_bundle_type_not_found_detail(*, bundle_type_id: int) -> dict[str, object]:
    return {
        "code": "bundle_type_not_found",
        "message": "BundleType not found",
        "bundle_type_id": int(bundle_type_id),
        "next_steps": ["use_existing_bundle_type_id"],
    }


def _build_warehouse_not_found_detail(*, warehouse_id: int) -> dict[str, object]:
    return {
        "code": "warehouse_not_found",
        "message": "Warehouse not found",
        "warehouse_id": int(warehouse_id),
        "next_steps": ["use_existing_warehouse_id"],
    }


def _build_no_bundle_recipe_detail(*, article_id: int, bundle_type_id: int) -> dict[str, object]:
    return {
        "code": "no_bundle_recipe",
        "message": "No bundle recipe defined for this article and bundle type",
        "article_id": int(article_id),
        "bundle_type_id": int(bundle_type_id),
        "next_steps": ["create_bundle_recipe_for_bundle_type"],
    }


def calculate_bundle_availability(
    db: Session,
    article_id: int,
    bundle_type_id: int,
    warehouse_id: int,
) -> BundleAvailabilityResponse:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_article_not_found_detail(article_id=article_id),
        )

    bundle_type = db.query(BundleType).filter(BundleType.id == bundle_type_id).first()
    if bundle_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_bundle_type_not_found_detail(bundle_type_id=bundle_type_id),
        )

    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if warehouse is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_build_warehouse_not_found_detail(warehouse_id=warehouse_id),
        )

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
            detail=_build_no_bundle_recipe_detail(
                article_id=article_id,
                bundle_type_id=bundle_type_id,
            ),
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

    if not size_to_color_sku:
        return BundleAvailabilityResponse(
            article_id=article_id,
            bundle_type_id=bundle_type_id,
            warehouse_id=warehouse_id,
            total_available=0,
            per_size=[],
        )

    size_ids = list(size_to_color_sku.keys())
    sizes = db.query(Size).filter(Size.id.in_(size_ids)).all()
    size_map = {s.id: s for s in sizes}

    balances = (
        db.query(StockBalance)
        .filter(
            StockBalance.warehouse_id == warehouse_id,
            StockBalance.sku_unit_id.in_([sku.id for sku in sku_units]),
        )
        .all()
    )
    balance_map: dict[int, int] = {b.sku_unit_id: b.quantity for b in balances}

    per_size: list[BundleAvailabilityPerSize] = []
    total_available = 0

    for size_id, color_sku_map in size_to_color_sku.items():
        size_obj = size_map.get(size_id)
        if size_obj is None:
            # Size record missing; treat as unavailable
            per_size.append(
                BundleAvailabilityPerSize(
                    size_id=size_id,
                    size_label=str(size_id),
                    available=0,
                )
            )
            continue

        # Ensure all colors from the recipe exist for this size
        if not recipe_color_ids.issubset(color_sku_map.keys()):
            available = 0
        else:
            quantities: list[int] = []
            for color_id in recipe_color_ids:
                sku_unit = color_sku_map[color_id]
                quantity = balance_map.get(sku_unit.id, 0)
                quantities.append(max(quantity, 0))

            available = min(quantities) if quantities else 0

        per_size.append(
            BundleAvailabilityPerSize(
                size_id=size_id,
                size_label=size_obj.label,
                available=available,
            )
        )
        total_available += available

    per_size.sort(key=lambda x: x.size_id)

    return BundleAvailabilityResponse(
        article_id=article_id,
        bundle_type_id=bundle_type_id,
        warehouse_id=warehouse_id,
        total_available=total_available,
        per_size=per_size,
    )
