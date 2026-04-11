from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.wb import (
    ArticleWbMappingImportRequest,
    WbImportSummary,
    WbFromWbReadinessRequest,
    WbFromWbReadinessSummary,
    WbLiveCommissionSyncRequest,
    WbLiveCommissionSyncSummary,
    WbLiveArticleBootstrapRequest,
    WbLiveArticleBootstrapSummary,
    WbLiveMappingDiscoverRequest,
    WbLiveMappingDiscoverSummary,
    WbLiveMappingSyncRequest,
    WbLiveMappingSyncSummary,
    WbLiveSupplySyncRequest,
    WbLiveSupplySyncSummary,
    WbLiveSyncRequest,
    WbLiveSyncSummary,
    WbSalesDailyImportRequest,
    WbStockImportRequest,
)
from app.services.wb_ingest import (
    bootstrap_articles_from_wb_api,
    discover_article_mapping_from_wb_api,
    get_from_wb_readiness_summary,
    load_sales_daily,
    load_stock,
    map_bundles_to_sku,
    sync_commission_from_wb_api,
    sync_article_mapping_from_wb_api,
    sync_sales_daily_from_wb_api,
    sync_supplies_from_wb_api,
    sync_stock_from_wb_api,
)


router = APIRouter()


@router.post("/sales-daily/import", response_model=WbImportSummary)
def import_wb_sales_daily(
    payload: WbSalesDailyImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return load_sales_daily(db=db, items=payload.items)


@router.post("/sales-daily/sync-live", response_model=WbLiveSyncSummary)
def sync_wb_sales_daily_live(
    payload: WbLiveSyncRequest,
    db: Session = Depends(get_db),
) -> WbLiveSyncSummary:
    return sync_sales_daily_from_wb_api(
        db=db,
        account_id=payload.account_id,
        date_from=payload.date_from,
        max_pages=payload.max_pages,
    )


@router.post("/stock/import", response_model=WbImportSummary)
def import_wb_stock(
    payload: WbStockImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return load_stock(db=db, items=payload.items)


@router.post("/stock/sync-live", response_model=WbLiveSyncSummary)
def sync_wb_stock_live(
    payload: WbLiveSyncRequest,
    db: Session = Depends(get_db),
) -> WbLiveSyncSummary:
    return sync_stock_from_wb_api(
        db=db,
        account_id=payload.account_id,
        date_from=payload.date_from,
        max_pages=payload.max_pages,
    )


@router.post("/article-mapping/import", response_model=WbImportSummary)
def import_article_wb_mapping(
    payload: ArticleWbMappingImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return map_bundles_to_sku(db=db, items=payload.items)


@router.post("/article-mapping/sync-live", response_model=WbLiveMappingSyncSummary)
def sync_wb_article_mapping_live(
    payload: WbLiveMappingSyncRequest,
    db: Session = Depends(get_db),
) -> WbLiveMappingSyncSummary:
    return sync_article_mapping_from_wb_api(
        db=db,
        account_id=payload.account_id,
        date_from=payload.date_from,
        max_pages=payload.max_pages,
        default_bundle_type_id=payload.default_bundle_type_id,
    )


@router.post("/article-mapping/discover-live", response_model=WbLiveMappingDiscoverSummary)
def discover_wb_article_mapping_live(
    payload: WbLiveMappingDiscoverRequest,
    db: Session = Depends(get_db),
) -> WbLiveMappingDiscoverSummary:
    return discover_article_mapping_from_wb_api(
        db=db,
        account_id=payload.account_id,
        date_from=payload.date_from,
        max_pages=payload.max_pages,
        limit=payload.limit,
    )


@router.post("/article/bootstrap-live", response_model=WbLiveArticleBootstrapSummary)
def bootstrap_wb_articles_live(
    payload: WbLiveArticleBootstrapRequest,
    db: Session = Depends(get_db),
) -> WbLiveArticleBootstrapSummary:
    return bootstrap_articles_from_wb_api(
        db=db,
        account_id=payload.account_id,
        date_from=payload.date_from,
        max_pages=payload.max_pages,
        limit=payload.limit,
        dry_run=payload.dry_run,
    )


@router.post("/from-wb/readiness", response_model=WbFromWbReadinessSummary)
def get_wb_from_wb_readiness(
    payload: WbFromWbReadinessRequest,
    db: Session = Depends(get_db),
) -> WbFromWbReadinessSummary:
    return get_from_wb_readiness_summary(
        db=db,
        article_id=payload.article_id,
        limit=payload.limit,
        request_sales_stale_after_days=payload.freshness_sales_stale_after_days,
        request_stock_stale_after_days=payload.freshness_stock_stale_after_days,
    )


@router.post("/commission/sync-live", response_model=WbLiveCommissionSyncSummary)
def sync_wb_commission_live(
    payload: WbLiveCommissionSyncRequest,
    db: Session = Depends(get_db),
) -> WbLiveCommissionSyncSummary:
    return sync_commission_from_wb_api(
        db=db,
        account_id=payload.account_id,
        top_subjects_limit=payload.top_subjects_limit,
    )


@router.post("/supplies/sync-live", response_model=WbLiveSupplySyncSummary)
def sync_wb_supplies_live(
    payload: WbLiveSupplySyncRequest,
    db: Session = Depends(get_db),
) -> WbLiveSupplySyncSummary:
    return sync_supplies_from_wb_api(
        db=db,
        account_id=payload.account_id,
        limit=payload.limit,
        is_closed=payload.is_closed,
    )
