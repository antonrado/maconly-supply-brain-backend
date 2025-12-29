from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.wb import (
    ArticleWbMappingImportRequest,
    WbImportSummary,
    WbSalesDailyImportRequest,
    WbStockImportRequest,
)
from app.services.wb_ingest import (
    load_sales_daily,
    load_stock,
    map_bundles_to_sku,
)


router = APIRouter()


@router.post("/sales-daily/import", response_model=WbImportSummary)
def import_wb_sales_daily(
    payload: WbSalesDailyImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return load_sales_daily(db=db, items=payload.items)


@router.post("/stock/import", response_model=WbImportSummary)
def import_wb_stock(
    payload: WbStockImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return load_stock(db=db, items=payload.items)


@router.post("/article-mapping/import", response_model=WbImportSummary)
def import_article_wb_mapping(
    payload: ArticleWbMappingImportRequest,
    db: Session = Depends(get_db),
) -> WbImportSummary:
    return map_bundles_to_sku(db=db, items=payload.items)
