from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import ArticlePlanningSettings

FROM_WB_SALES_STALE_AFTER_DAYS = 3
FROM_WB_STOCK_STALE_AFTER_DAYS = 2


def parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_from_wb_freshness_thresholds(
    *,
    request_sales_stale_after_days: int | None,
    request_stock_stale_after_days: int | None,
    admin_sales_stale_after_days: int | None,
    admin_stock_stale_after_days: int | None,
) -> tuple[int, int, dict[str, str]]:
    if request_sales_stale_after_days is not None:
        sales_stale_after_days = int(request_sales_stale_after_days)
        sales_source = "request"
    elif admin_sales_stale_after_days is not None:
        sales_stale_after_days = int(admin_sales_stale_after_days)
        sales_source = "admin_defaults"
    else:
        sales_stale_after_days = FROM_WB_SALES_STALE_AFTER_DAYS
        sales_source = "global_default"

    if request_stock_stale_after_days is not None:
        stock_stale_after_days = int(request_stock_stale_after_days)
        stock_source = "request"
    elif admin_stock_stale_after_days is not None:
        stock_stale_after_days = int(admin_stock_stale_after_days)
        stock_source = "admin_defaults"
    else:
        stock_stale_after_days = FROM_WB_STOCK_STALE_AFTER_DAYS
        stock_source = "global_default"

    return (
        sales_stale_after_days,
        stock_stale_after_days,
        {
            "sales": sales_source,
            "stock": stock_source,
        },
    )


def build_from_wb_freshness_snapshot(
    *,
    effective_as_of_date: date | None,
    wb_stock_updated_at_by_bundle: dict[int, str | None],
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    now: datetime,
) -> tuple[str, int | None, int | None, dict[int, int | None]]:
    anchor_date = now.date()

    sales_age_days_value: int | None = None
    if effective_as_of_date is not None:
        sales_age_days_value = max((anchor_date - effective_as_of_date).days, 0)

    stock_age_days_by_bundle: dict[int, int | None] = {}
    for bundle_type_id, updated_at_text in wb_stock_updated_at_by_bundle.items():
        updated_at = parse_iso_datetime(updated_at_text)
        if updated_at is None:
            stock_age_days_by_bundle[bundle_type_id] = None
            continue

        stock_age_days_by_bundle[bundle_type_id] = max((anchor_date - updated_at.date()).days, 0)

    stock_known_ages = [age for age in stock_age_days_by_bundle.values() if age is not None]
    stock_oldest_age_days_value = max(stock_known_ages) if stock_known_ages else None

    stale_sales = (
        sales_age_days_value is not None
        and sales_age_days_value > sales_stale_after_days
    )
    stale_stock = (
        stock_oldest_age_days_value is not None
        and stock_oldest_age_days_value > stock_stale_after_days
    )

    if sales_age_days_value is None and stock_oldest_age_days_value is None:
        freshness_status = "no_data"
    elif sales_age_days_value is None:
        freshness_status = "missing_sales_data"
    elif stock_oldest_age_days_value is None:
        freshness_status = "missing_stock_data"
    elif stale_sales or stale_stock:
        freshness_status = "stale"
    else:
        freshness_status = "fresh"

    return (
        freshness_status,
        sales_age_days_value,
        stock_oldest_age_days_value,
        stock_age_days_by_bundle,
    )


def _resolve_from_wb_freshness_thresholds(
    db: Session,
    article_id: int,
    request_sales_stale_after_days: int | None,
    request_stock_stale_after_days: int | None,
) -> tuple[int, int, dict[str, str]]:
    article_settings = (
        db.query(ArticlePlanningSettings)
        .filter(ArticlePlanningSettings.article_id == article_id)
        .first()
    )

    admin_sales_stale_after_days = (
        int(article_settings.production_order_freshness_sales_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_sales_stale_after_days is not None
        else None
    )
    admin_stock_stale_after_days = (
        int(article_settings.production_order_freshness_stock_stale_after_days)
        if article_settings is not None
        and article_settings.production_order_freshness_stock_stale_after_days is not None
        else None
    )

    return resolve_from_wb_freshness_thresholds(
        request_sales_stale_after_days=request_sales_stale_after_days,
        request_stock_stale_after_days=request_stock_stale_after_days,
        admin_sales_stale_after_days=admin_sales_stale_after_days,
        admin_stock_stale_after_days=admin_stock_stale_after_days,
    )


def build_from_wb_freshness_next_steps(
    *,
    freshness_status: str,
    sales_age_days: int | None,
    stock_oldest_age_days: int | None,
    sales_stale_after_days: int,
    stock_stale_after_days: int,
) -> list[str]:
    stale_sales = sales_age_days is not None and sales_age_days > sales_stale_after_days
    stale_stock = stock_oldest_age_days is not None and stock_oldest_age_days > stock_stale_after_days

    if freshness_status == "no_data":
        return [
            "run_wb_sales_daily_sync_live",
            "run_wb_stock_sync_live",
        ]
    if freshness_status == "missing_sales_data":
        next_steps = ["run_wb_sales_daily_sync_live"]
        if stale_stock:
            next_steps.append("run_wb_stock_sync_live")
        return next_steps
    if freshness_status == "missing_stock_data":
        next_steps = ["run_wb_stock_sync_live"]
        if stale_sales:
            next_steps.insert(0, "run_wb_sales_daily_sync_live")
        return next_steps
    if stale_sales and stale_stock:
        return [
            "run_wb_sales_daily_sync_live",
            "run_wb_stock_sync_live",
        ]
    if stale_sales:
        return ["run_wb_sales_daily_sync_live"]
    if stale_stock:
        return ["run_wb_stock_sync_live"]
    return []


def build_from_wb_freshness_blocker(
    *,
    freshness_status: str,
    sales_age_days: int | None,
    stock_oldest_age_days: int | None,
    sales_stale_after_days: int,
    stock_stale_after_days: int,
) -> str | None:
    stale_sales = sales_age_days is not None and sales_age_days > sales_stale_after_days
    stale_stock = stock_oldest_age_days is not None and stock_oldest_age_days > stock_stale_after_days

    if freshness_status == "no_data":
        return "no_wb_sales_or_stock_data"
    if freshness_status == "missing_sales_data":
        return "no_wb_sales_data"
    if freshness_status == "missing_stock_data":
        return "no_wb_stock_data"
    if stale_sales and stale_stock:
        return "stale_wb_sales_and_stock_data"
    if stale_sales:
        return "stale_wb_sales_data"
    if stale_stock:
        return "stale_wb_stock_data"
    return None


def _raise_from_wb_strict_freshness_failure_if_needed(
    *,
    article_id: int,
    freshness_mode: str,
    freshness_status: str,
    sales_age_days: int | None,
    stock_oldest_age_days: int | None,
    sales_stale_after_days: int,
    stock_stale_after_days: int,
    threshold_source: dict[str, object],
    build_from_wb_freshness_failure_detail: Callable[..., dict[str, object]],
) -> None:
    if freshness_mode != "strict" or freshness_status == "fresh":
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=build_from_wb_freshness_failure_detail(
            article_id=article_id,
            freshness_status=freshness_status,
            freshness_mode=freshness_mode,
            sales_age_days=sales_age_days,
            stock_oldest_age_days=stock_oldest_age_days,
            sales_stale_after_days=sales_stale_after_days,
            stock_stale_after_days=stock_stale_after_days,
            threshold_source=threshold_source,
        ),
    )
