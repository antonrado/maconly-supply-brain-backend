from __future__ import annotations

from pydantic import BaseModel


class NskSkuStockSnapshot(BaseModel):
    color_id: int
    size_id: int
    quantity: int


class WbBundleStockSnapshot(BaseModel):
    bundle_type_id: int
    bundle_type_name: str
    size_id: int
    quantity: int


class NskBundleStockSnapshot(BaseModel):
    bundle_type_id: int
    bundle_type_name: str
    size_id: int
    quantity: int


class BundleCoverageSnapshot(BaseModel):
    bundle_type_id: int
    bundle_type_name: str
    avg_daily_sales: float | None = None
    wb_ready_bundles: int
    nsk_ready_bundles: int
    potential_bundles_from_singles: int
    total_available_bundles: int
    days_of_cover: float | None = None
    observation_window_days: int | None = None


class ArticleInventorySnapshot(BaseModel):
    article_id: int
    article_code: str

    nsk_single_sku_stock: list[NskSkuStockSnapshot]
    wb_bundle_stock: list[WbBundleStockSnapshot]
    nsk_bundle_stock: list[NskBundleStockSnapshot]

    bundle_coverage: list[BundleCoverageSnapshot]
