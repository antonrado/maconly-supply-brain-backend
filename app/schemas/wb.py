from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


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


class WbLiveSyncRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    date_from: datetime | None = None
    max_pages: int = Field(default=5, ge=1, le=100)


class WbLiveMappingSyncRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    date_from: datetime | None = None
    max_pages: int = Field(default=5, ge=1, le=100)
    default_bundle_type_id: int | None = Field(default=None, ge=1)


class WbLiveMappingDiscoverRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    date_from: datetime | None = None
    max_pages: int = Field(default=5, ge=1, le=100)
    limit: int = Field(default=50, ge=1, le=500)


class WbLiveArticleBootstrapRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    date_from: datetime | None = None
    max_pages: int = Field(default=5, ge=1, le=100)
    limit: int = Field(default=50, ge=1, le=500)
    dry_run: bool = True


class WbFromWbReadinessRequest(BaseModel):
    article_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=1000)


class WbLiveCommissionSyncRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    top_subjects_limit: int = Field(default=20, ge=1, le=200)


class WbLiveSupplySyncRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=1000)
    is_closed: bool | None = None


class WbLiveSyncSummary(BaseModel):
    account_id: int
    fetched_rows: int
    inserted: int
    updated: int
    pages_requested: int
    pages_with_data: int
    date_from_effective: str
    next_cursor: str | None = None


class WbLiveMappingSyncSummary(BaseModel):
    account_id: int
    fetched_rows: int
    pages_requested: int
    pages_with_data: int
    date_from_effective: str
    next_cursor: str | None = None
    candidate_pairs: int
    matched_pairs: int
    unmatched_pairs: int
    exact_matched_pairs: int
    normalized_matched_pairs: int
    ambiguous_normalized_pairs: int
    inserted: int
    updated: int


class WbLiveMappingDiscoverItem(BaseModel):
    supplier_article: str
    rows: int
    unique_wb_skus: int
    match_source: str
    matched_article_id: int | None = None
    matched_article_code: str | None = None


class WbLiveMappingDiscoverSummary(BaseModel):
    account_id: int
    fetched_rows: int
    pages_requested: int
    pages_with_data: int
    date_from_effective: str
    next_cursor: str | None = None
    unique_supplier_articles: int
    matched_supplier_articles: int
    unmatched_supplier_articles: int
    ambiguous_supplier_articles: int
    items: list[WbLiveMappingDiscoverItem]


class WbLiveArticleBootstrapItem(BaseModel):
    supplier_article: str
    rows: int
    status: str
    article_id: int | None = None


class WbLiveArticleBootstrapSummary(BaseModel):
    account_id: int
    fetched_rows: int
    pages_requested: int
    pages_with_data: int
    date_from_effective: str
    next_cursor: str | None = None
    candidate_supplier_articles: int
    existing_articles: int
    inserted_articles: int
    skipped_invalid: int
    dry_run: bool
    items: list[WbLiveArticleBootstrapItem]


class WbFromWbReadinessItem(BaseModel):
    article_id: int
    article_code: str
    mapped_wb_skus: int
    mapped_wb_skus_with_sales: int
    mapped_wb_skus_with_stock: int
    mapped_bundle_type_ids: list[int]
    recipe_bundle_type_ids: list[int]
    missing_recipe_bundle_type_ids: list[int]
    ready_for_from_wb: bool
    blocker: str | None = None
    next_steps: list[str] = Field(default_factory=list)


class WbFromWbReadinessSummary(BaseModel):
    total_articles_considered: int
    ready_articles: int
    not_ready_articles: int
    items: list[WbFromWbReadinessItem]


class WbLiveCommissionSubjectItem(BaseModel):
    subject_id: int | None = None
    subject_name: str
    kgvp_supplier_percent: float | None = None


class WbLiveCommissionSyncSummary(BaseModel):
    account_id: int
    fetched_rows: int
    subjects_with_commission: int
    avg_kgvp_supplier_percent: float | None = None
    min_kgvp_supplier_percent: float | None = None
    max_kgvp_supplier_percent: float | None = None
    subjects: list[WbLiveCommissionSubjectItem]


class WbLiveSupplyStatusItem(BaseModel):
    supply_id: int
    status_id: int | None = None
    create_date: str | None = None
    supply_date: str | None = None
    updated_date: str | None = None


class WbLiveSupplySyncSummary(BaseModel):
    account_id: int
    fetched_rows: int
    status_counts: dict[str, int]
    supplies: list[WbLiveSupplyStatusItem]
