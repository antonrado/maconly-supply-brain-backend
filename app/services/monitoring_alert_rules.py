from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import MonitoringAlertRule
from app.schemas.monitoring_alerts import AlertRuleCreate, AlertRuleUpdate


def list_alert_rules(db: Session) -> list[MonitoringAlertRule]:
    return db.query(MonitoringAlertRule).order_by(MonitoringAlertRule.id).all()


def create_alert_rule(db: Session, data: AlertRuleCreate) -> MonitoringAlertRule:
    rule = MonitoringAlertRule(
        name=data.name,
        metric=data.metric,
        threshold_type=data.threshold_type,
        threshold_value=data.threshold_value,
        severity=data.severity,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_alert_rule(
    db: Session,
    rule_id: int,
    data: AlertRuleUpdate,
) -> MonitoringAlertRule | None:
    rule = (
        db.query(MonitoringAlertRule)
        .filter(MonitoringAlertRule.id == rule_id)
        .first()
    )
    if rule is None:
        return None

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return rule


def delete_alert_rule(db: Session, rule_id: int) -> bool:
    rule = (
        db.query(MonitoringAlertRule)
        .filter(MonitoringAlertRule.id == rule_id)
        .first()
    )
    if rule is None:
        return False

    db.delete(rule)
    db.commit()
    return True
