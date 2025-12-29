from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import ArticlePlanningSettings, GlobalPlanningSettings, ArticleWbMapping, WbSalesDaily, WbStock
from app.schemas.demand import DemandResult


OBSERVATION_WINDOW_DAYS = 30


def compute_demand(db: Session, article_id: int, target_date: date) -> DemandResult:
    """Compute demand metrics for a given article on WB data."""

    explanation_parts: list[str] = []

    # Map article to WB SKUs
    mappings = (
        db.query(ArticleWbMapping)
        .filter(ArticleWbMapping.article_id == article_id)
        .all()
    )
    wb_skus = sorted({m.wb_sku for m in mappings})

    if not wb_skus:
        explanation_parts.append(
            "No WB SKU mappings (article_wb_mapping) found for this article; "
            "treating sales and stock as zero."
        )

    # Aggregate sales over observation window
    start_date = target_date - timedelta(days=OBSERVATION_WINDOW_DAYS - 1)
    total_sales = 0
    days_with_sales = 0

    if wb_skus:
        total_sales, days_with_sales = (
            db.query(
                func.coalesce(func.sum(WbSalesDaily.sales_qty), 0),
                func.count(func.distinct(WbSalesDaily.date)),
            )
            .filter(
                WbSalesDaily.wb_sku.in_(wb_skus),
                WbSalesDaily.date >= start_date,
                WbSalesDaily.date <= target_date,
            )
            .one()
        )

        total_sales = int(total_sales or 0)
        days_with_sales = int(days_with_sales or 0)

    if days_with_sales > 0:
        obs_days_used = min(OBSERVATION_WINDOW_DAYS, days_with_sales)
    else:
        obs_days_used = OBSERVATION_WINDOW_DAYS

    if obs_days_used > 0 and total_sales > 0:
        avg_daily_sales = float(total_sales) / float(obs_days_used)
    else:
        avg_daily_sales = 0.0

    if days_with_sales == 0:
        explanation_parts.append(
            f"No WB sales in the last {OBSERVATION_WINDOW_DAYS} days; "
            "avg_daily_sales set to 0."
        )
    elif days_with_sales < OBSERVATION_WINDOW_DAYS:
        explanation_parts.append(
            f"Sales history is shorter than {OBSERVATION_WINDOW_DAYS} days "
            f"({days_with_sales} days with data); avg_daily_sales is computed "
            f"over {obs_days_used} actual days with sales."
        )

    # Determine forecast horizon from ArticlePlanningSettings/GlobalPlanningSettings
    aps = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )

    gps = db.query(GlobalPlanningSettings).first()
    fallback_target_coverage = gps.default_target_coverage_days if gps else 60

    if aps is not None and aps.target_coverage_days is not None:
        target_coverage_days = aps.target_coverage_days
        explanation_parts.append(
            f"Using article-specific target_coverage_days={target_coverage_days} "
            "from ArticlePlanningSettings."
        )
    else:
        target_coverage_days = fallback_target_coverage
        explanation_parts.append(
            f"ArticlePlanningSettings.target_coverage_days is not set; "
            f"using GlobalPlanningSettings.default_target_coverage_days="
            f"{target_coverage_days}."
        )

    forecast_horizon_days = target_coverage_days

    # Forecast demand
    forecast_demand = avg_daily_sales * float(forecast_horizon_days)

    # Current WB stock
    current_stock = 0
    if wb_skus:
        current_stock = (
            db.query(func.coalesce(func.sum(WbStock.stock_qty), 0))
            .filter(WbStock.wb_sku.in_(wb_skus))
            .scalar()
            or 0
        )
        current_stock = int(current_stock)

    # Coverage in days
    if avg_daily_sales > 0:
        coverage_days = float(current_stock) / float(avg_daily_sales)
    else:
        coverage_days = 9999.0
        explanation_parts.append(
            "avg_daily_sales is 0; coverage_days set to a large sentinel value (9999)."
        )

    # Deficit based on forecast demand
    raw_deficit = forecast_demand - float(current_stock)
    deficit = int(raw_deficit) if raw_deficit > 0 else 0

    explanation_parts.append(
        "Computed demand metrics: "
        f"wb_skus={len(wb_skus)}, total_sales={total_sales} over {obs_days_used} days, "
        f"avg_daily_sales={avg_daily_sales:.3f}, forecast_horizon_days={forecast_horizon_days}, "
        f"forecast_demand={forecast_demand:.3f}, current_stock={current_stock}, "
        f"coverage_days={coverage_days:.3f}, deficit={deficit}."
    )

    explanation = " ".join(explanation_parts) if explanation_parts else None

    return DemandResult(
        article_id=article_id,
        avg_daily_sales=avg_daily_sales,
        forecast_demand=forecast_demand,
        current_stock=current_stock,
        coverage_days=coverage_days,
        deficit=deficit,
        target_coverage_days=target_coverage_days,
        observation_window_days=OBSERVATION_WINDOW_DAYS,
        forecast_horizon_days=forecast_horizon_days,
        explanation=explanation,
    )
