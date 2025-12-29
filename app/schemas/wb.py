from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class WbSalesDailyItem(BaseModel):
    wb_sku: str
    date: date
    sales_qty: int = 0
    revenue: float | None = None


class WbSalesDailyImportRequest(BaseModel):
    items: list[WbSalesDailyItem]


class WbStockItem(BaseModel):
    wb_sku: str
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    stock_qty: int
    updated_at: datetime | None = None


class WbStockImportRequest(BaseModel):
    items: list[WbStockItem]


class ArticleWbMappingItem(BaseModel):
    article_id: int
    wb_sku: str
    bundle_type_id: int | None = None
    color_id: int | None = None
    size_id: int | None = None


class ArticleWbMappingImportRequest(BaseModel):
    items: list[ArticleWbMappingItem]


class WbImportSummary(BaseModel):
    inserted: int
    updated: int
