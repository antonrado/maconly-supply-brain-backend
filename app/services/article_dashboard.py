from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.article_dashboard import ArticleDashboardResponse
from app.schemas.bundle_risk import ArticleBundleRiskEntry
from app.schemas.order_explanation import ArticleOrderExplanation
from app.schemas.planning_health import ArticleHealthSummary
from app.services.bundle_risk import build_bundle_risk_portfolio
from app.services.order_explanation import build_order_explanation_portfolio
from app.services.planning_health import build_planning_health_portfolio


def _find_first_by_article_id(entries, article_id: int):
    for entry in entries:
        if entry.article_id == article_id:
            return entry
    return None


def build_article_dashboard(db: Session, article_id: int) -> Optional[ArticleDashboardResponse]:
    risk_portfolio = build_bundle_risk_portfolio(db=db, article_ids=[article_id])
    order_portfolio = build_order_explanation_portfolio(db=db, article_ids=[article_id])
    health_portfolio = build_planning_health_portfolio(db=db, article_ids=[article_id])

    risk_entry: Optional[ArticleBundleRiskEntry] = _find_first_by_article_id(risk_portfolio, article_id)
    order_entry: Optional[ArticleOrderExplanation] = _find_first_by_article_id(order_portfolio, article_id)
    health_entry: Optional[ArticleHealthSummary] = _find_first_by_article_id(health_portfolio, article_id)

    if risk_entry is None and order_entry is None and health_entry is None:
        return None

    article_code: str | None = None
    bundle_type_id: int | None = None
    bundle_type_name: str | None = None

    if order_entry is not None:
        article_code = order_entry.article_code
    elif risk_entry is not None:
        article_code = risk_entry.article_code
    elif health_entry is not None:
        article_code = health_entry.article_code

    if risk_entry is not None:
        bundle_type_id = risk_entry.bundle_type_id
        bundle_type_name = risk_entry.bundle_type_name

    return ArticleDashboardResponse(
        article_id=article_id,
        article_code=article_code,
        bundle_type_id=bundle_type_id,
        bundle_type_name=bundle_type_name,
        risk=risk_entry,
        order=order_entry,
        health=health_entry,
    )
