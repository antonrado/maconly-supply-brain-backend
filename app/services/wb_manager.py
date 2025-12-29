from __future__ import annotations

from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Article,
    Color,
    Size,
    SkuUnit,
    ArticleWbMapping,
    WbSalesDaily,
    WbStock,
)
from app.schemas.wb_manager import WbManagerSkuStats, WbWarehouseStockItem


OBSERVATION_WINDOW_DAYS = 30


def compute_manager_stats(
    db: Session,
    target_date: date,
    article_ids: list[int] | None = None,
) -> list[WbManagerSkuStats]:
    """Compute WB manager dashboard stats per SKU (article/color/size).

    WB sales and stock are aggregated per article across all mapped WB SKUs.
    The aggregated numbers are then repeated for each SKU of the article.
    """

    # Base query: all SKU units with joined article/color/size
    query = (
        db.query(SkuUnit, Article, Color, Size)
        .join(Article, SkuUnit.article_id == Article.id)
        .join(Color, SkuUnit.color_id == Color.id)
        .join(Size, SkuUnit.size_id == Size.id)
    )
    if article_ids:
        query = query.filter(SkuUnit.article_id.in_(article_ids))

    sku_rows = query.all()
    if not sku_rows:
        return []

    # Collect involved article_ids
    article_ids_set: set[int] = {sku.article_id for (sku, _a, _c, _s) in sku_rows}

    # Load mappings article -> WB SKUs
    mappings = (
        db.query(ArticleWbMapping)
        .filter(ArticleWbMapping.article_id.in_(article_ids_set))
        .all()
    )

    article_to_skus: dict[int, list[str]] = defaultdict(list)
    wb_sku_to_article: dict[str, int] = {}
    for m in mappings:
        article_to_skus[m.article_id].append(m.wb_sku)
        wb_sku_to_article[m.wb_sku] = m.article_id

    article_data: dict[int, dict] = {}
    for article_id in article_ids_set:
        article_data[article_id] = {
            "wb_skus": article_to_skus.get(article_id, []),
            "has_mapping": bool(article_to_skus.get(article_id)),
            "sales_1d": 0,
            "sales_7d": 0,
            "sales_30d": 0,
            "stock_total": 0,
            "stock_by_wh": defaultdict(int),  # (warehouse_id, warehouse_name) -> qty
        }

    # Time windows
    start_30d = target_date - timedelta(days=OBSERVATION_WINDOW_DAYS - 1)
    start_7d = target_date - timedelta(days=7 - 1)

    # Aggregate sales over 30 days for all mapped WB SKUs
    all_wb_skus: set[str] = {wb_sku for skus in article_to_skus.values() for wb_sku in skus}

    if all_wb_skus:
        sales_rows = (
            db.query(WbSalesDaily.wb_sku, WbSalesDaily.date, WbSalesDaily.sales_qty)
            .filter(
                WbSalesDaily.wb_sku.in_(all_wb_skus),
                WbSalesDaily.date >= start_30d,
                WbSalesDaily.date <= target_date,
            )
            .all()
        )

        for wb_sku, row_date, qty in sales_rows:
            article_id = wb_sku_to_article.get(wb_sku)
            if article_id is None:
                continue
            data = article_data.get(article_id)
            if data is None:
                continue
            qty_int = int(qty or 0)
            data["sales_30d"] += qty_int
            if row_date >= start_7d:
                data["sales_7d"] += qty_int
            if row_date == target_date:
                data["sales_1d"] += qty_int

        # Aggregate stock for all mapped WB SKUs
        stock_rows = (
            db.query(
                WbStock.wb_sku,
                WbStock.warehouse_id,
                WbStock.warehouse_name,
                WbStock.stock_qty,
            )
            .filter(WbStock.wb_sku.in_(all_wb_skus))
            .all()
        )

        for wb_sku, wh_id, wh_name, qty in stock_rows:
            article_id = wb_sku_to_article.get(wb_sku)
            if article_id is None:
                continue
            data = article_data.get(article_id)
            if data is None:
                continue
            qty_int = int(qty or 0)
            data["stock_total"] += qty_int
            key = (wh_id, wh_name)
            data["stock_by_wh"][key] += qty_int

    # Build per-SKU stats
    results: list[WbManagerSkuStats] = []

    for sku, article, color, size in sku_rows:
        data = article_data.get(sku.article_id)
        if data is None:
            # Should not happen, but treat as article without mapping and data
            wb_skus_for_article: list[str] = []
            has_mapping = False
            sales_1d = sales_7d = sales_30d = 0
            stock_total = 0
            stock_by_wh = {}
        else:
            wb_skus_for_article = data["wb_skus"]
            has_mapping = data["has_mapping"]
            sales_1d = int(data["sales_1d"])
            sales_7d = int(data["sales_7d"])
            sales_30d = int(data["sales_30d"])
            stock_total = int(data["stock_total"])
            stock_by_wh = data["stock_by_wh"]

        if sales_30d > 0:
            avg_daily_sales_30d = float(sales_30d) / float(OBSERVATION_WINDOW_DAYS)
        else:
            avg_daily_sales_30d = 0.0

        forecast_7d = avg_daily_sales_30d * 7.0
        forecast_30d = avg_daily_sales_30d * 30.0

        if avg_daily_sales_30d > 0:
            coverage_days = float(stock_total) / float(avg_daily_sales_30d)
        else:
            if stock_total > 0:
                coverage_days = 9999.0
            else:
                coverage_days = 0.0

        # OOS risk level
        if stock_total == 0 and avg_daily_sales_30d > 0:
            oos_risk = "red"
        elif avg_daily_sales_30d > 0:
            if coverage_days < 3:
                oos_risk = "red"
            elif coverage_days <= 7:
                oos_risk = "yellow"
            else:
                oos_risk = "green"
        else:
            # avg_daily_sales_30d == 0
            if stock_total == 0:
                oos_risk = "green"
            else:
                oos_risk = "green"

        # WB SKU field semantics
        unique_skus = sorted(set(wb_skus_for_article))
        if len(unique_skus) == 1:
            wb_sku_value: str | None = unique_skus[0]
        else:
            wb_sku_value = None

        # Stock by warehouse list
        wb_stock_items: list[WbWarehouseStockItem] = []
        for (wh_id, wh_name), qty in sorted(
            stock_by_wh.items(), key=lambda kv: (kv[0][0] or -1, kv[0][1] or "")
        ):
            wb_stock_items.append(
                WbWarehouseStockItem(
                    warehouse_id=wh_id,
                    warehouse_name=wh_name,
                    stock_qty=int(qty or 0),
                )
            )

        # Explanation
        explanation_parts: list[str] = []
        if not has_mapping:
            explanation_parts.append(
                "No WB SKU mapping (article_wb_mapping) for this article; treating WB sales and stock as zero."
            )
        explanation_parts.append(
            "Metrics: "
            f"sales_30d={sales_30d}, avg_daily_sales_30d={avg_daily_sales_30d:.3f}, "
            f"wb_stock_total={stock_total}, coverage_days={coverage_days:.1f}. "
            f"Risk level={oos_risk} (thresholds: <3 red, 3-7 yellow, >7 green)."
        )
        explanation = " ".join(explanation_parts)

        stats = WbManagerSkuStats(
            article_id=article.id,
            article_code=article.code,
            color_id=color.id if color is not None else None,
            color_inner_code=color.inner_code if color is not None else None,
            size_id=size.id if size is not None else None,
            size_label=size.label if size is not None else None,
            wb_sku=wb_sku_value,
            wb_stock_total=stock_total,
            wb_stock_by_warehouse=wb_stock_items,
            observation_window_days=OBSERVATION_WINDOW_DAYS,
            sales_1d=sales_1d,
            sales_7d=sales_7d,
            sales_30d=sales_30d,
            avg_daily_sales_30d=avg_daily_sales_30d,
            forecast_7d=forecast_7d,
            forecast_30d=forecast_30d,
            coverage_days=coverage_days,
            oos_risk_level=oos_risk,
            explanation=explanation,
        )
        results.append(stats)

    return results
