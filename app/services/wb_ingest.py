from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.models import Article, ArticleWbMapping, WbSalesDaily, WbStock
from app.schemas.wb import (
    ArticleWbMappingItem,
    WbImportSummary,
    WbSalesDailyItem,
    WbStockItem,
)


def _utcnow() -> datetime:
    """Helper to get timezone-aware UTC now for updated_at default."""
    return datetime.now(timezone.utc)


def load_sales_daily(db: Session, items: list[WbSalesDailyItem]) -> WbImportSummary:
    """Upsert WB daily sales into wb_sales_daily.

    - If (wb_sku, date) exists: update sales_qty and revenue.
    - Else: insert new row.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    keys = {(i.wb_sku, i.date) for i in items}
    if not keys:
        return WbImportSummary(inserted=0, updated=0)

    all_skus = {k[0] for k in keys}
    all_dates = {k[1] for k in keys}

    existing_rows: list[WbSalesDaily] = (
        db.query(WbSalesDaily)
        .filter(WbSalesDaily.wb_sku.in_(all_skus), WbSalesDaily.date.in_(all_dates))
        .all()
    )
    existing_map: dict[tuple[str, datetime.date], WbSalesDaily] = {
        (row.wb_sku, row.date): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.wb_sku, item.date)
        row = existing_map.get(key)
        if row is None:
            row = WbSalesDaily(
                wb_sku=item.wb_sku,
                date=item.date,
                sales_qty=item.sales_qty,
                revenue=item.revenue,
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.sales_qty = item.sales_qty
            row.revenue = item.revenue
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def load_stock(db: Session, items: list[WbStockItem]) -> WbImportSummary:
    """Upsert WB stock balances into wb_stock.

    For each (wb_sku, warehouse_id):
    - If exists: overwrite stock_qty, updated_at (v1: simple overwrite policy).
    - Else: insert new row.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    keys = {(i.wb_sku, i.warehouse_id) for i in items}
    if not keys:
        return WbImportSummary(inserted=0, updated=0)

    all_skus = {k[0] for k in keys}
    all_warehouses = {k[1] for k in keys}

    non_null_warehouses = {wid for wid in all_warehouses if wid is not None}

    query = db.query(WbStock).filter(WbStock.wb_sku.in_(all_skus))
    if non_null_warehouses:
        query = query.filter(
            or_(
                WbStock.warehouse_id.in_(non_null_warehouses),
                WbStock.warehouse_id.is_(None) if None in all_warehouses else False,
            )
        )
    elif None in all_warehouses:
        query = query.filter(WbStock.warehouse_id.is_(None))

    existing_rows: list[WbStock] = query.all()
    existing_map: dict[tuple[str, int | None], WbStock] = {
        (row.wb_sku, row.warehouse_id): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.wb_sku, item.warehouse_id)
        row = existing_map.get(key)
        value_updated_at = item.updated_at or _utcnow()
        if row is None:
            row = WbStock(
                wb_sku=item.wb_sku,
                warehouse_id=item.warehouse_id,
                warehouse_name=item.warehouse_name,
                stock_qty=item.stock_qty,
                updated_at=value_updated_at,
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.warehouse_name = item.warehouse_name
            row.stock_qty = item.stock_qty
            row.updated_at = value_updated_at
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def map_bundles_to_sku(
    db: Session,
    items: list[ArticleWbMappingItem],
) -> WbImportSummary:
    """Upsert article → WB SKU mappings into article_wb_mapping.

    - Validate that all article_id exist; on first missing article raise 400.
    - For (article_id, wb_sku): update or insert mapping.
    All changes are committed in a single transaction.
    """
    if not items:
        return WbImportSummary(inserted=0, updated=0)

    article_ids = {i.article_id for i in items}
    if not article_ids:
        return WbImportSummary(inserted=0, updated=0)

    existing_articles: list[Article] = (
        db.query(Article).filter(Article.id.in_(article_ids)).all()
    )
    valid_article_ids = {a.id for a in existing_articles}

    for item in items:
        if item.article_id not in valid_article_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"article_id={item.article_id} for wb_sku={item.wb_sku} "
                    "does not exist in article table"
                ),
            )

    keys = {(i.article_id, i.wb_sku) for i in items}
    all_mapping_article_ids = {k[0] for k in keys}
    all_wb_skus = {k[1] for k in keys}

    existing_rows: list[ArticleWbMapping] = (
        db.query(ArticleWbMapping)
        .filter(
            ArticleWbMapping.article_id.in_(all_mapping_article_ids),
            ArticleWbMapping.wb_sku.in_(all_wb_skus),
        )
        .all()
    )
    existing_map: dict[tuple[int, str], ArticleWbMapping] = {
        (row.article_id, row.wb_sku): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for item in items:
        key = (item.article_id, item.wb_sku)
        row = existing_map.get(key)
        if row is None:
            row = ArticleWbMapping(
                article_id=item.article_id,
                wb_sku=item.wb_sku,
                bundle_type_id=item.bundle_type_id,
                color_id=item.color_id,
                size_id=item.size_id,
            )
            db.add(row)
            existing_map[key] = row
            inserted += 1
        else:
            row.bundle_type_id = item.bundle_type_id
            row.color_id = item.color_id
            row.size_id = item.size_id
            updated += 1

    db.commit()
    return WbImportSummary(inserted=inserted, updated=updated)


def sync_all() -> None:
    """Placeholder for running full WB data sync (sales, stock, mappings).

    Not used by HTTP API in TASK #12.
    """
    pass
