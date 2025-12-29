from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import MonitoringAlertRule, MonitoringSnapshotRecord
from app.schemas.monitoring_alerts import ActiveAlertSchema
from app.services.monitoring import build_monitoring_snapshot
from app.services.monitoring_history import get_monitoring_history  # noqa: F401


SUPPORTED_METRICS = {
    "risk_critical",
    "risk_warning",
    "risk_ok",
    "risk_overstock",
    "risk_no_data",
    "wb_accounts_active",
    "ms_accounts_active",
    "articles_with_orders",
    "total_final_order_qty",
}


def _get_current_snapshot_values(db: Session) -> dict[str, int]:
    latest = (
        db.query(MonitoringSnapshotRecord)
        .order_by(MonitoringSnapshotRecord.created_at.desc(), MonitoringSnapshotRecord.id.desc())
        .first()
    )

    values: dict[str, int]

    if latest is not None:
        values = {
            "risk_critical": latest.risk_critical,
            "risk_warning": latest.risk_warning,
            "risk_ok": latest.risk_ok,
            "risk_overstock": latest.risk_overstock,
            "risk_no_data": latest.risk_no_data,
            "wb_accounts_active": latest.wb_accounts_active,
            "ms_accounts_active": latest.ms_accounts_active,
            "articles_with_orders": latest.articles_with_orders,
            "total_final_order_qty": latest.total_final_order_qty,
        }
    else:
        snapshot = build_monitoring_snapshot(db=db)
        values = {
            "risk_critical": snapshot.risks.critical,
            "risk_warning": snapshot.risks.warning,
            "risk_ok": snapshot.risks.ok,
            "risk_overstock": snapshot.risks.overstock,
            "risk_no_data": snapshot.risks.no_data,
            "wb_accounts_active": snapshot.integrations.wb_accounts_active,
            "ms_accounts_active": snapshot.integrations.ms_accounts_active,
            "articles_with_orders": snapshot.orders.articles_with_orders,
            "total_final_order_qty": snapshot.orders.total_final_order_qty,
        }

    return values


def evaluate_active_alerts(db: Session) -> list[ActiveAlertSchema]:
    values = _get_current_snapshot_values(db)

    rules = (
        db.query(MonitoringAlertRule)
        .filter(MonitoringAlertRule.is_active.is_(True))
        .all()
    )

    active_alerts: list[ActiveAlertSchema] = []

    for rule in rules:
        if rule.metric not in values:
            continue

        current_value = values[rule.metric]
        triggered = False

        if rule.threshold_type == "above":
            triggered = current_value > rule.threshold_value
        elif rule.threshold_type == "below":
            triggered = current_value < rule.threshold_value
        else:
            triggered = False

        if not triggered:
            continue

        active_alerts.append(
            ActiveAlertSchema(
                rule_id=rule.id,
                name=rule.name,
                severity=rule.severity,
                metric=rule.metric,
                current_value=current_value,
                threshold_type=rule.threshold_type,
                threshold_value=rule.threshold_value,
            )
        )

    return active_alerts
