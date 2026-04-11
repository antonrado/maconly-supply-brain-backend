from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import BundleRecipe, SkuUnit, StockBalance
from app.schemas.planning_production_order import ProductionOrderProposalRequest


@dataclass(frozen=True)
class _PreparedProductionOrderInputs:
    bundle_type_ids: list[int]
    recipe_colors_by_bundle: dict[int, set[int]]
    all_recipe_color_ids: list[int]
    sku_by_color_size: dict[tuple[int, int], SkuUnit]
    color_to_sizes: dict[int, list[int]]
    size_ids: list[int]
    size_weights_source: str
    size_weights: dict[int, float]
    stock_by_color_size: dict[tuple[int, int], int]
    current_stock_by_color_size: dict[tuple[int, int], int]
    in_flight_source: str
    in_flight_raw_qty_total: int
    in_flight_effective_qty_total: int
    in_flight_effective_lines: int
    in_flight_effective_by_color_size: dict[tuple[int, int], int]
    in_flight_eta_days_by_color_size: dict[tuple[int, int], int]
    demand_by_bundle: dict[int, float]
    total_daily_sales: float
    bundle_stock_source: str
    ready_bundle_stock_total: int
    shares_by_bundle: dict[int, float]


def _prepare_production_order_inputs(
    *,
    db: Session,
    request: ProductionOrderProposalRequest,
    lead_time_days_total: int,
    load_admin_size_weights: Callable[..., dict[int, float]],
    load_admin_in_flight_defaults: Callable[..., list[object]],
    normalize_weights: Callable[[list[int], dict[int, float]], dict[int, float]],
    estimate_effective_in_flight_qty: Callable[..., int],
    load_wb_bundle_stock: Callable[..., dict[int, int]],
    build_direct_missing_bundle_recipe_detail: Callable[..., dict[str, object]],
    build_direct_missing_sku_scope_detail: Callable[..., dict[str, object]],
) -> _PreparedProductionOrderInputs:
    bundle_type_ids = sorted({item.bundle_type_id for item in request.bundle_daily_sales})

    recipes = (
        db.query(BundleRecipe)
        .filter(
            BundleRecipe.article_id == request.article_id,
            BundleRecipe.bundle_type_id.in_(bundle_type_ids),
        )
        .all()
    )

    if not recipes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_direct_missing_bundle_recipe_detail(
                article_id=request.article_id,
                requested_bundle_type_ids=bundle_type_ids,
                missing_bundle_type_ids=bundle_type_ids,
            ),
        )

    recipe_colors_by_bundle: dict[int, set[int]] = defaultdict(set)
    for recipe in recipes:
        recipe_colors_by_bundle[recipe.bundle_type_id].add(recipe.color_id)

    missing_bundle_types = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if not recipe_colors_by_bundle.get(bundle_type_id)
    ]
    if missing_bundle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_direct_missing_bundle_recipe_detail(
                article_id=request.article_id,
                requested_bundle_type_ids=bundle_type_ids,
                missing_bundle_type_ids=missing_bundle_types,
            ),
        )

    all_recipe_color_ids = sorted(
        {color_id for colors in recipe_colors_by_bundle.values() for color_id in colors}
    )

    sku_units = (
        db.query(SkuUnit)
        .filter(
            SkuUnit.article_id == request.article_id,
            SkuUnit.color_id.in_(all_recipe_color_ids),
        )
        .all()
    )

    if not sku_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_direct_missing_sku_scope_detail(
                article_id=request.article_id,
                requested_bundle_type_ids=bundle_type_ids,
                recipe_color_ids=all_recipe_color_ids,
            ),
        )

    sku_by_color_size: dict[tuple[int, int], SkuUnit] = {}
    color_to_sizes: dict[int, list[int]] = defaultdict(list)
    size_ids_set: set[int] = set()
    for sku in sku_units:
        sku_by_color_size[(sku.color_id, sku.size_id)] = sku
        color_to_sizes[sku.color_id].append(sku.size_id)
        size_ids_set.add(sku.size_id)

    size_ids = sorted(size_ids_set)
    for color_id in color_to_sizes:
        color_to_sizes[color_id] = sorted(set(color_to_sizes[color_id]))

    requested_size_weights = {
        int(size_id): float(weight)
        for size_id, weight in request.size_weights.items()
        if weight > 0
    }
    size_weights_source = "request"
    if not requested_size_weights:
        requested_size_weights = load_admin_size_weights(
            db=db,
            article_id=request.article_id,
            size_ids=size_ids,
        )
        if requested_size_weights:
            size_weights_source = "admin_defaults"
        else:
            size_weights_source = "uniform_fallback"

    size_weights = normalize_weights(size_ids, requested_size_weights)

    stock_agg_rows = (
        db.query(
            StockBalance.sku_unit_id,
            func.sum(StockBalance.quantity).label("total_qty"),
        )
        .filter(StockBalance.sku_unit_id.in_([sku.id for sku in sku_units]))
        .group_by(StockBalance.sku_unit_id)
        .all()
    )
    stock_by_sku_id = {
        int(row.sku_unit_id): max(int(row.total_qty or 0), 0) for row in stock_agg_rows
    }

    stock_by_color_size: dict[tuple[int, int], int] = {}
    for sku in sku_units:
        stock_by_color_size[(sku.color_id, sku.size_id)] = stock_by_sku_id.get(sku.id, 0)
    current_stock_by_color_size = dict(stock_by_color_size)

    effective_in_flight_supply = list(request.in_flight_supply)
    in_flight_source = "request"

    if not effective_in_flight_supply:
        admin_defaults = load_admin_in_flight_defaults(
            db=db,
            article_id=request.article_id,
        )
        if admin_defaults:
            in_flight_source = "admin_defaults"
            for row in admin_defaults:
                effective_in_flight_supply.append(row)
        else:
            in_flight_source = "none"

    in_flight_raw_qty_total = 0
    in_flight_effective_qty_total = 0
    in_flight_effective_lines = 0
    in_flight_effective_by_color_size: dict[tuple[int, int], int] = defaultdict(int)
    in_flight_eta_days_by_color_size: dict[tuple[int, int], int] = {}

    for in_flight in effective_in_flight_supply:
        if in_flight.article_id != request.article_id:
            continue

        key = (in_flight.color_id, in_flight.size_id)
        if key not in sku_by_color_size:
            continue

        raw_qty = max(int(in_flight.qty), 0)
        if raw_qty <= 0:
            continue

        in_flight_raw_qty_total += raw_qty
        eta_days = int(in_flight.eta_days)
        existing_eta = in_flight_eta_days_by_color_size.get(key)
        if existing_eta is None or eta_days < existing_eta:
            in_flight_eta_days_by_color_size[key] = eta_days

        effective_qty = estimate_effective_in_flight_qty(
            qty=raw_qty,
            eta_days=eta_days,
            lead_time_days_total=lead_time_days_total,
            stage=getattr(in_flight, "stage", "other"),
        )
        if effective_qty <= 0:
            continue

        in_flight_effective_qty_total += effective_qty
        in_flight_effective_lines += 1
        in_flight_effective_by_color_size[key] += effective_qty
        stock_by_color_size[key] = stock_by_color_size.get(key, 0) + effective_qty

    demand_by_bundle = {
        item.bundle_type_id: item.daily_sales for item in request.bundle_daily_sales
    }
    total_daily_sales = float(sum(demand_by_bundle.values()))

    stock_by_bundle = {
        item.bundle_type_id: item.wb_qty + item.local_qty for item in request.bundle_stock
    }
    bundle_stock_source = "request"

    missing_bundle_type_ids = [
        bundle_type_id
        for bundle_type_id in bundle_type_ids
        if bundle_type_id not in stock_by_bundle
    ]
    if missing_bundle_type_ids:
        wb_bundle_stock = load_wb_bundle_stock(
            db=db,
            article_id=request.article_id,
            bundle_type_ids=missing_bundle_type_ids,
        )
        for bundle_type_id in missing_bundle_type_ids:
            if bundle_type_id in wb_bundle_stock:
                stock_by_bundle[bundle_type_id] = wb_bundle_stock[bundle_type_id]

        if wb_bundle_stock:
            if request.bundle_stock:
                bundle_stock_source = "mixed_request_plus_wb"
            else:
                bundle_stock_source = "wb_defaults"
        elif not request.bundle_stock:
            bundle_stock_source = "none"

    ready_bundle_stock_total = sum(
        stock_by_bundle.get(bundle_type_id, 0) for bundle_type_id in bundle_type_ids
    )

    shares_by_bundle: dict[int, float] = {}
    if total_daily_sales > 0:
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = (
                demand_by_bundle.get(bundle_type_id, 0.0) / total_daily_sales
            )
    else:
        equal_share = 1.0 / len(bundle_type_ids)
        for bundle_type_id in bundle_type_ids:
            shares_by_bundle[bundle_type_id] = equal_share

    return _PreparedProductionOrderInputs(
        bundle_type_ids=bundle_type_ids,
        recipe_colors_by_bundle=dict(recipe_colors_by_bundle),
        all_recipe_color_ids=all_recipe_color_ids,
        sku_by_color_size=sku_by_color_size,
        color_to_sizes=dict(color_to_sizes),
        size_ids=size_ids,
        size_weights_source=size_weights_source,
        size_weights=size_weights,
        stock_by_color_size=stock_by_color_size,
        current_stock_by_color_size=current_stock_by_color_size,
        in_flight_source=in_flight_source,
        in_flight_raw_qty_total=in_flight_raw_qty_total,
        in_flight_effective_qty_total=in_flight_effective_qty_total,
        in_flight_effective_lines=in_flight_effective_lines,
        in_flight_effective_by_color_size=dict(in_flight_effective_by_color_size),
        in_flight_eta_days_by_color_size=in_flight_eta_days_by_color_size,
        demand_by_bundle=demand_by_bundle,
        total_daily_sales=total_daily_sales,
        bundle_stock_source=bundle_stock_source,
        ready_bundle_stock_total=ready_bundle_stock_total,
        shares_by_bundle=shares_by_bundle,
    )
