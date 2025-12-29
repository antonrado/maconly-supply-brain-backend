from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.bundle_risk import ArticleBundleRiskEntry
from app.schemas.monitoring_risk_focus import MonitoringTopRiskItem
from app.services.bundle_risk import build_bundle_risk_portfolio


RISK_PRIORITY: dict[str, int] = {
    "critical": 0,
    "warning": 1,
    "no_data": 2,
    "ok": 3,
    "overstock": 4,
}


def _get_risk_level_value(entry: ArticleBundleRiskEntry) -> str:
    level = entry.risk_level
    if hasattr(level, "value"):
        return level.value  # Enum case
    return str(level)


def build_top_risky_articles(
    db: Session,
    limit: int,
) -> list[MonitoringTopRiskItem]:
    portfolio = build_bundle_risk_portfolio(db=db, article_ids=None)

    if not portfolio:
        return []

    def _sort_key(entry: ArticleBundleRiskEntry) -> tuple[int, int, int | None, str]:
        level_value = _get_risk_level_value(entry)
        priority = RISK_PRIORITY.get(level_value, len(RISK_PRIORITY))
        return priority, entry.article_id, entry.bundle_type_id, entry.article_code

    sorted_entries = sorted(portfolio, key=_sort_key)
    top_entries = sorted_entries[:limit]

    items: list[MonitoringTopRiskItem] = []
    for entry in top_entries:
        level_value = _get_risk_level_value(entry)
        items.append(
            MonitoringTopRiskItem(
                article_id=entry.article_id,
                article_code=entry.article_code,
                bundle_type_id=entry.bundle_type_id,
                bundle_type_name=entry.bundle_type_name,
                risk_level=level_value,
                days_of_cover=entry.days_of_cover,
                final_order_qty=None,
            )
        )

    return items
