from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    ArticleWbMapping,
    BundleRecipe,
    BundleType,
    SkuUnit,
    StockBalance,
    Warehouse,
    WbSalesDaily,
    WbStock,
)
from app.schemas.article_bundle_snapshot import (
    ArticleInventorySnapshot,
    BundleCoverageSnapshot,
    NskBundleStockSnapshot,
    NskSkuStockSnapshot,
    WbBundleStockSnapshot,
)
from app.services.bundle_planning import calculate_bundle_availability


CapacityKey = Tuple[int, int]  # (bundle_type_id, size_id)


def compute_bundle_capacity_for_article(db: Session, article_id: int) -> Dict[CapacityKey, int]:
    """Compute max number of bundles from NSC single-stock per (bundle_type, size).

    Reuses calculate_bundle_availability for the first internal (NSC) warehouse.
    Returns a mapping (bundle_type_id, size_id) -> capacity.
    """

    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    nsk_warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.type == "internal")
        .order_by(Warehouse.id)
        .first()
    )
    if nsk_warehouse is None:
        # No internal warehouse configured; no capacity from singles
        return {}

    bundle_type_rows = (
        db.query(BundleRecipe.bundle_type_id)
        .filter(BundleRecipe.article_id == article_id)
        .distinct()
        .all()
    )
    bundle_type_ids = [row[0] for row in bundle_type_rows]
    if not bundle_type_ids:
        return {}

    capacities: Dict[CapacityKey, int] = {}
    for bundle_type_id in bundle_type_ids:
        availability = calculate_bundle_availability(
            db=db,
            article_id=article_id,
            bundle_type_id=bundle_type_id,
            warehouse_id=nsk_warehouse.id,
        )
        for per_size in availability.per_size:
            capacities[(bundle_type_id, per_size.size_id)] = per_size.available

    return capacities


def compute_bundle_sales_stats(
    db: Session,
    article_id: int,
    bundle_type_id: int,
    observation_window_days: int = 30,
    as_of_date: date | None = None,
) -> float:
    """Compute average daily WB bundle sales for a given article & bundle type.

    Sales are taken from WbSalesDaily using wb_sku values from ArticleWbMapping
    where bundle_type_id matches. We consider the last `observation_window_days`
    days up to `as_of_date` (inclusive). If `as_of_date` is not provided, we use
    the maximum sales date for the relevant wb_skus.

    The average is calculated as:

        avg_daily_sales = total_sales_qty / days_in_window

    where `days_in_window` is the inclusive span between the earliest and latest
    sales dates in the observation window (min_date..max_date). If there are no
    sales rows in the window, the function returns 0.0.
    """

    if observation_window_days <= 0:
        return 0.0

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article_id,
            ArticleWbMapping.bundle_type_id == bundle_type_id,
        )
        .all()
    )

    if not mappings:
        return 0.0

    wb_skus = {m.wb_sku for m in mappings}
    if not wb_skus:
        return 0.0

    max_date_q = (
        db.query(func.max(WbSalesDaily.date))
        .filter(WbSalesDaily.wb_sku.in_(wb_skus))
    )
    max_sales_date: date | None = max_date_q.scalar()

    if max_sales_date is None:
        return 0.0

    if as_of_date is None:
        as_of_date = max_sales_date

    start_cutoff = as_of_date - timedelta(days=observation_window_days - 1)

    sales_rows = (
        db.query(WbSalesDaily)
        .filter(
            WbSalesDaily.wb_sku.in_(wb_skus),
            WbSalesDaily.date >= start_cutoff,
            WbSalesDaily.date <= as_of_date,
        )
        .all()
    )

    if not sales_rows:
        return 0.0

    total_sales_qty = sum(r.sales_qty for r in sales_rows)
    min_date = min(r.date for r in sales_rows)
    max_date = max(r.date for r in sales_rows)
    days_in_window = (max_date - min_date).days + 1
    if days_in_window <= 0:
        return 0.0

    return float(total_sales_qty) / float(days_in_window)


def build_article_inventory_snapshot(db: Session, article_id: int) -> ArticleInventorySnapshot:
    """Assemble ArticleInventorySnapshot for a single article.

    This is a read-only view over existing bundles-related data:
    - NSC single-SKU stock (internal warehouses)
    - WB bundle stock (via ArticleWbMapping + WbStock)
    - Bundle capacity from singles on NSC using existing bundle_planning logic
    - Aggregate bundle coverage per bundle type
    """

    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    # NSK single SKU stock (raw singles by color/size across internal warehouses)
    sku_units = db.query(SkuUnit).filter(SkuUnit.article_id == article.id).all()
    nsk_single_sku_stock: list[NskSkuStockSnapshot] = []
    if sku_units:
        sku_ids = [s.id for s in sku_units]
        sku_to_color = {s.id: s.color_id for s in sku_units}
        sku_to_size = {s.id: s.size_id for s in sku_units}

        balances_with_wh = (
            db.query(StockBalance, Warehouse)
            .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
            .filter(
                StockBalance.sku_unit_id.in_(sku_ids),
                Warehouse.type == "internal",
            )
            .all()
        )

        qty_by_pair: Dict[Tuple[int, int], int] = defaultdict(int)
        for balance, _wh in balances_with_wh:
            color_id = sku_to_color.get(balance.sku_unit_id)
            size_id = sku_to_size.get(balance.sku_unit_id)
            if color_id is None or size_id is None:
                continue
            qty_by_pair[(color_id, size_id)] += balance.quantity

        nsk_single_sku_stock = [
            NskSkuStockSnapshot(
                color_id=color_id,
                size_id=size_id,
                quantity=qty,
            )
            for (color_id, size_id), qty in sorted(qty_by_pair.items())
        ]

    # WB bundle stock (via ArticleWbMapping.bundle_type_id and WbStock)
    wb_bundle_stock: list[WbBundleStockSnapshot] = []

    mappings = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id == article.id,
            ArticleWbMapping.bundle_type_id.is_not(None),
        )
        .all()
    )

    if mappings:
        wb_skus = {m.wb_sku for m in mappings}
        stock_rows = db.query(WbStock).filter(WbStock.wb_sku.in_(wb_skus)).all()
        qty_by_sku: Dict[str, int] = defaultdict(int)
        for row in stock_rows:
            qty_by_sku[row.wb_sku] += row.stock_qty

        qty_by_bt_size: Dict[Tuple[int, int], int] = defaultdict(int)
        bundle_type_ids: set[int] = set()
        for m in mappings:
            if m.bundle_type_id is None or m.size_id is None:
                continue
            bundle_type_ids.add(m.bundle_type_id)
            qty = qty_by_sku.get(m.wb_sku, 0)
            qty_by_bt_size[(m.bundle_type_id, m.size_id)] += qty

        bundle_type_map: Dict[int, str] = {}
        if bundle_type_ids:
            for bt in db.query(BundleType).filter(BundleType.id.in_(bundle_type_ids)).all():
                bundle_type_map[bt.id] = bt.name

        wb_bundle_stock = [
            WbBundleStockSnapshot(
                bundle_type_id=bt_id,
                bundle_type_name=bundle_type_map.get(bt_id, str(bt_id)),
                size_id=size_id,
                quantity=qty,
            )
            for (bt_id, size_id), qty in sorted(qty_by_bt_size.items())
        ]

    # NSC bundle stock: there is no dedicated entity for assembled bundles on NSC yet
    nsk_bundle_stock: list[NskBundleStockSnapshot] = []

    # Bundle capacity from singles (NSC)
    capacity_by_bt_size = compute_bundle_capacity_for_article(db=db, article_id=article.id)

    # Aggregate bundle coverage per bundle_type
    wb_ready_by_type: Dict[int, int] = defaultdict(int)
    for s in wb_bundle_stock:
        wb_ready_by_type[s.bundle_type_id] += s.quantity

    potential_by_type: Dict[int, int] = defaultdict(int)
    for (bt_id, _size_id), cap in capacity_by_bt_size.items():
        potential_by_type[bt_id] += cap

    bundle_type_ids_union = set(wb_ready_by_type.keys()) | set(potential_by_type.keys())

    bundle_type_map: Dict[int, str] = {}
    if bundle_type_ids_union:
        for bt in db.query(BundleType).filter(BundleType.id.in_(bundle_type_ids_union)).all():
            bundle_type_map[bt.id] = bt.name

    observation_window_days = 30

    bundle_coverage: list[BundleCoverageSnapshot] = []
    for bt_id in sorted(bundle_type_ids_union):
        wb_ready = wb_ready_by_type.get(bt_id, 0)
        nsk_ready = 0  # Assembled NSC bundles are not modeled yet
        potential = potential_by_type.get(bt_id, 0)
        total = wb_ready + nsk_ready + potential

        avg_daily_sales = compute_bundle_sales_stats(
            db=db,
            article_id=article.id,
            bundle_type_id=bt_id,
            observation_window_days=observation_window_days,
            as_of_date=None,
        )
        if avg_daily_sales > 0:
            days_of_cover = total / avg_daily_sales if total > 0 else 0.0
        else:
            days_of_cover = None

        bundle_coverage.append(
            BundleCoverageSnapshot(
                bundle_type_id=bt_id,
                bundle_type_name=bundle_type_map.get(bt_id, str(bt_id)),
                avg_daily_sales=avg_daily_sales,
                wb_ready_bundles=wb_ready,
                nsk_ready_bundles=nsk_ready,
                potential_bundles_from_singles=potential,
                total_available_bundles=total,
                days_of_cover=days_of_cover,
                observation_window_days=observation_window_days,
            )
        )

    return ArticleInventorySnapshot(
        article_id=article.id,
        article_code=article.code,
        nsk_single_sku_stock=nsk_single_sku_stock,
        wb_bundle_stock=wb_bundle_stock,
        nsk_bundle_stock=nsk_bundle_stock,
        bundle_coverage=bundle_coverage,
    )
