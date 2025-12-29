from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.monitoring import MonitoringSnapshot
from app.schemas.monitoring_dashboard import MonitoringStatusResponse, MonitoringStatusSummary
from app.services.monitoring import build_monitoring_snapshot
from app.services.monitoring_alerts import evaluate_active_alerts


def _compute_overall_status_from_alerts_and_snapshot(
    critical_count: int,
    warning_count: int,
    snapshot: MonitoringSnapshot,
) -> str:
    if critical_count > 0:
        return "critical"
    if warning_count > 0:
        return "warning"

    if snapshot.risks.critical > 0:
        return "warning"

    integrations = snapshot.integrations
    if integrations.wb_accounts_active == 0 or integrations.ms_accounts_active == 0:
        return "warning"

    return "ok"


def build_monitoring_status_summary(db: Session) -> tuple[MonitoringStatusSummary, datetime]:
    alert_items = evaluate_active_alerts(db=db)

    critical_count = sum(1 for alert in alert_items if alert.severity == "critical")
    warning_count = sum(1 for alert in alert_items if alert.severity == "warning")

    snapshot = build_monitoring_snapshot(db=db)
    updated_at = snapshot.updated_at

    overall_status = _compute_overall_status_from_alerts_and_snapshot(
        critical_count=critical_count,
        warning_count=warning_count,
        snapshot=snapshot,
    )

    status_summary = MonitoringStatusSummary(
        overall_status=overall_status,
        critical_alerts=critical_count,
        warning_alerts=warning_count,
    )

    return status_summary, updated_at


def build_monitoring_status(db: Session) -> MonitoringStatusResponse:
    """Build a full MonitoringStatusResponse using the existing summary logic.

    This helper reuses build_monitoring_status_summary to keep the core
    status computation (alerts + snapshot) in a single place and only
    wraps it into the public MonitoringStatusResponse schema.
    """
    status_summary, updated_at = build_monitoring_status_summary(db=db)
    return MonitoringStatusResponse(
        overall_status=status_summary.overall_status,
        critical_alerts=status_summary.critical_alerts,
        warning_alerts=status_summary.warning_alerts,
        updated_at=updated_at,
    )
