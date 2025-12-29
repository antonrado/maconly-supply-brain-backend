from __future__ import annotations

from typing import List, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import PlanningSettings
from app.schemas.article_bundle_snapshot import ArticleInventorySnapshot
from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.services.article_bundle_snapshot import build_article_inventory_snapshot

DEFAULT_SAFETY_STOCK_DAYS = 7
DEFAULT_ALERT_THRESHOLD_DAYS = 14
OVERSTOCK_MULTIPLIER = 3


def resolve_thresholds_for_article(
    db: Session,
    article_id: int,
) -> tuple[int | None, int | None, int | None]:
    """Return (safety_stock_days, alert_threshold_days, overstock_threshold_days) for an article.

    If there is a PlanningSettings row for the article, use its safety/alert thresholds.
    Otherwise fall back to temporary global defaults defined in this module.
    Overstock threshold is derived as alert_threshold_days * OVERSTOCK_MULTIPLIER.
    """

    ps = (
        db.query(PlanningSettings)
        .filter(PlanningSettings.article_id == article_id)
        .first()
    )

    if ps is not None:
        safety_stock_days = ps.safety_stock_days
        alert_threshold_days = ps.alert_threshold_days
    else:
        safety_stock_days = DEFAULT_SAFETY_STOCK_DAYS
        alert_threshold_days = DEFAULT_ALERT_THRESHOLD_DAYS

    overstock_threshold_days: int | None
    if alert_threshold_days is not None:
        overstock_threshold_days = alert_threshold_days * OVERSTOCK_MULTIPLIER
    else:
        overstock_threshold_days = None

    return safety_stock_days, alert_threshold_days, overstock_threshold_days


def compute_risk_for_article_snapshot(
    db: Session,
    snapshot: ArticleInventorySnapshot,
) -> list[ArticleBundleRiskEntry]:
    """Compute risk entries per bundle type for a single article snapshot."""

    safety_stock_days, alert_threshold_days, overstock_threshold_days = resolve_thresholds_for_article(
        db=db,
        article_id=snapshot.article_id,
    )

    entries: list[ArticleBundleRiskEntry] = []

    for cov in snapshot.bundle_coverage:
        avg_daily_sales = cov.avg_daily_sales if cov.avg_daily_sales is not None else 0.0
        total_available = cov.total_available_bundles
        days_of_cover = cov.days_of_cover

        # Determine risk level
        if avg_daily_sales == 0.0:
            if total_available > 0:
                risk_level = BundleRiskLevel.OVERSTOCK
                explanation = (
                    f"avg_daily_sales=0.0, total_available={total_available}, "
                    f"no WB bundle sales observed in last {cov.observation_window_days} days -> status=overstock"
                )
            else:
                risk_level = BundleRiskLevel.NO_DATA
                explanation = (
                    "avg_daily_sales=0.0, total_available=0, "
                    "no stock and no WB bundle sales observed -> status=no_data"
                )
        else:
            # days_of_cover should normally be non-None if avg_daily_sales > 0
            if days_of_cover is None:
                risk_level = BundleRiskLevel.NO_DATA
                explanation = (
                    f"avg_daily_sales={avg_daily_sales:.2f}, total_available={total_available}, "
                    "days_of_cover is None -> status=no_data"
                )
            else:
                if safety_stock_days is not None and days_of_cover <= safety_stock_days:
                    risk_level = BundleRiskLevel.CRITICAL
                elif (
                    safety_stock_days is not None
                    and alert_threshold_days is not None
                    and safety_stock_days < days_of_cover <= alert_threshold_days
                ):
                    risk_level = BundleRiskLevel.WARNING
                elif (
                    alert_threshold_days is not None
                    and overstock_threshold_days is not None
                    and alert_threshold_days < days_of_cover < overstock_threshold_days
                ):
                    risk_level = BundleRiskLevel.OK
                elif overstock_threshold_days is not None and days_of_cover >= overstock_threshold_days:
                    risk_level = BundleRiskLevel.OVERSTOCK
                else:
                    risk_level = BundleRiskLevel.NO_DATA

                explanation = (
                    f"avg_daily_sales={avg_daily_sales:.2f}, total_available={total_available}, "
                    f"days_of_cover={days_of_cover:.2f}, "
                    f"safety_stock_days={safety_stock_days}, "
                    f"alert_threshold_days={alert_threshold_days}, "
                    f"overstock_threshold_days={overstock_threshold_days} "
                    f"-> status={risk_level.value}"
                )

        entries.append(
            ArticleBundleRiskEntry(
                article_id=snapshot.article_id,
                article_code=snapshot.article_code,
                bundle_type_id=cov.bundle_type_id,
                bundle_type_name=cov.bundle_type_name,
                avg_daily_sales=avg_daily_sales,
                total_available_bundles=total_available,
                days_of_cover=days_of_cover,
                risk_level=risk_level,
                safety_stock_days=safety_stock_days,
                alert_threshold_days=alert_threshold_days,
                overstock_threshold_days=overstock_threshold_days,
                explanation=explanation,
            )
        )

    return entries


def build_bundle_risk_portfolio(
    db: Session,
    article_ids: list[int] | None = None,
) -> list[ArticleBundleRiskEntry]:
    """Build bundle risk portfolio for given articles or all active ones.

    If `article_ids` is None, all articles with PlanningSettings.is_active = True
    are used. If `article_ids` is provided, only these articles are considered;
    unknown article IDs are silently ignored.
    """

    target_article_ids: list[int]

    if article_ids is None:
        rows = (
            db.query(PlanningSettings.article_id)
            .filter(PlanningSettings.is_active.is_(True))
            .all()
        )
        target_article_ids = [row[0] for row in rows]
    else:
        # Deduplicate but keep order
        seen: set[int] = set()
        target_article_ids = []
        for aid in article_ids:
            if aid not in seen:
                seen.add(aid)
                target_article_ids.append(aid)

    portfolio: list[ArticleBundleRiskEntry] = []

    for article_id in target_article_ids:
        try:
            snapshot = build_article_inventory_snapshot(db=db, article_id=article_id)
        except HTTPException as exc:  # type: ignore[py310-no-except-type-comments]
            if exc.status_code == status.HTTP_404_NOT_FOUND and exc.detail == "Article not found":
                # Ignore unknown article IDs
                continue
            raise

        portfolio.extend(compute_risk_for_article_snapshot(db=db, snapshot=snapshot))

    return portfolio
