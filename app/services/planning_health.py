from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.schemas.bundle_risk import ArticleBundleRiskEntry, BundleRiskLevel
from app.schemas.order_explanation import ArticleOrderExplanation
from app.schemas.planning_health import ArticleHealthSummary
from app.services.bundle_risk import build_bundle_risk_portfolio
from app.services.order_explanation import build_order_explanation_portfolio


RISK_PRIORITY: dict[BundleRiskLevel, int] = {
    BundleRiskLevel.CRITICAL: 5,
    BundleRiskLevel.WARNING: 4,
    BundleRiskLevel.OK: 3,
    BundleRiskLevel.OVERSTOCK: 2,
    BundleRiskLevel.NO_DATA: 1,
}


def _aggregate_risk(entries: list[ArticleBundleRiskEntry]):
    if not entries:
        return {
            "worst_risk_level": None,
            "worst_risk_bundle_type_id": None,
            "worst_risk_bundle_type_name": None,
            "days_of_cover": None,
            "avg_daily_sales": None,
            "total_available_bundles": None,
            "has_critical": False,
            "has_warning": False,
        }

    worst_entry = max(entries, key=lambda e: RISK_PRIORITY[e.risk_level])

    has_critical = any(e.risk_level == BundleRiskLevel.CRITICAL for e in entries)
    has_warning = any(e.risk_level == BundleRiskLevel.WARNING for e in entries)

    return {
        "worst_risk_level": worst_entry.risk_level,
        "worst_risk_bundle_type_id": worst_entry.bundle_type_id,
        "worst_risk_bundle_type_name": worst_entry.bundle_type_name,
        "days_of_cover": worst_entry.days_of_cover,
        "avg_daily_sales": worst_entry.avg_daily_sales,
        "total_available_bundles": worst_entry.total_available_bundles,
        "has_critical": has_critical,
        "has_warning": has_warning,
    }


def _aggregate_orders(expl: ArticleOrderExplanation | None):
    if expl is None or not expl.reasons:
        return 0, None

    total_final_order_qty = sum(r.final_order_qty for r in expl.reasons)

    freq: dict[str, int] = defaultdict(int)
    for r in expl.reasons:
        if r.limiting_constraint is None:
            continue
        freq[r.limiting_constraint] += 1

    if not freq:
        return total_final_order_qty, None

    non_none_items = [(name, count) for name, count in freq.items() if name != "none"]

    if non_none_items:
        dominant = max(non_none_items, key=lambda x: x[1])[0]
    else:
        dominant = "none" if "none" in freq else None

    return total_final_order_qty, dominant


def build_planning_health_portfolio(
    db: Session,
    article_ids: list[int] | None = None,
) -> list[ArticleHealthSummary]:
    bundle_portfolio = build_bundle_risk_portfolio(db=db, article_ids=article_ids)
    order_portfolio = build_order_explanation_portfolio(db=db, article_ids=article_ids)

    risk_by_article: dict[int, list[ArticleBundleRiskEntry]] = defaultdict(list)
    for entry in bundle_portfolio:
        risk_by_article[entry.article_id].append(entry)

    orders_by_article: dict[int, ArticleOrderExplanation] = {}
    for expl in order_portfolio:
        orders_by_article[expl.article_id] = expl

    article_ids_union = set(risk_by_article.keys()) | set(orders_by_article.keys())

    items: list[ArticleHealthSummary] = []

    for article_id in sorted(article_ids_union):
        risk_entries = risk_by_article.get(article_id, [])
        order_expl = orders_by_article.get(article_id)

        if risk_entries:
            article_code = risk_entries[0].article_code
        elif order_expl is not None:
            article_code = order_expl.article_code
        else:
            continue

        risk_data = _aggregate_risk(risk_entries)
        total_final_order_qty, dominant_constraint = _aggregate_orders(order_expl)

        items.append(
            ArticleHealthSummary(
                article_id=article_id,
                article_code=article_code,
                worst_risk_level=risk_data["worst_risk_level"],
                worst_risk_bundle_type_id=risk_data["worst_risk_bundle_type_id"],
                worst_risk_bundle_type_name=risk_data["worst_risk_bundle_type_name"],
                days_of_cover=risk_data["days_of_cover"],
                avg_daily_sales=risk_data["avg_daily_sales"],
                total_available_bundles=risk_data["total_available_bundles"],
                total_final_order_qty=total_final_order_qty,
                dominant_limiting_constraint=dominant_constraint,
                has_critical=risk_data["has_critical"],
                has_warning=risk_data["has_warning"],
            )
        )

    return items
