from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.schemas.monitoring import IntegrationStatus, MonitoringSnapshot, OrderSummary, RiskSummary
from app.schemas.bundle_risk import BundleRiskLevel
from app.services.integrations_config import build_integrations_config_snapshot
from app.services.bundle_risk import build_bundle_risk_portfolio
from app.services.order_explanation import build_order_explanation_portfolio
from app.services.planning_health import build_planning_health_portfolio


def build_monitoring_snapshot(db: Session) -> MonitoringSnapshot:
    # Planning health is built for side-effects/consistency, even if not yet exposed directly
    _health_items = build_planning_health_portfolio(db=db)

    integrations_snapshot = build_integrations_config_snapshot(db=db)
    wb_accounts = integrations_snapshot.wb_accounts
    ms_accounts = integrations_snapshot.moysklad_accounts

    integrations = IntegrationStatus(
        wb_accounts_total=len(wb_accounts),
        wb_accounts_active=sum(1 for acc in wb_accounts if acc.is_active),
        ms_accounts_total=len(ms_accounts),
        ms_accounts_active=sum(1 for acc in ms_accounts if acc.is_active),
    )

    risk_entries = build_bundle_risk_portfolio(db=db)

    def _count(level: BundleRiskLevel) -> int:
        return sum(1 for e in risk_entries if e.risk_level == level)

    risks = RiskSummary(
        critical=_count(BundleRiskLevel.CRITICAL),
        warning=_count(BundleRiskLevel.WARNING),
        ok=_count(BundleRiskLevel.OK),
        overstock=_count(BundleRiskLevel.OVERSTOCK),
        no_data=_count(BundleRiskLevel.NO_DATA),
    )

    order_portfolio = build_order_explanation_portfolio(db=db)

    articles_with_orders = 0
    total_final_order_qty = 0
    for expl in order_portfolio:
        article_total = sum(r.final_order_qty for r in expl.reasons)
        if article_total > 0:
            articles_with_orders += 1
            total_final_order_qty += article_total

    orders = OrderSummary(
        articles_with_orders=articles_with_orders,
        total_final_order_qty=total_final_order_qty,
    )

    return MonitoringSnapshot(
        integrations=integrations,
        risks=risks,
        orders=orders,
        updated_at=datetime.now(timezone.utc),
    )
